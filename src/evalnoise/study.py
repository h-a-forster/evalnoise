"""The variance-components study over the committed trial tables (configs/study.toml).

Each dataset is one unit: estimates, bootstrap intervals, REML cross-check and planning
tables are written to ``<out>/units/<id>.json`` atomically. A unit is skipped on rerun when
its key (config entry, profile and input-table hash) is unchanged, so an interrupted study
resumes where it stopped. Progress goes to ``<out>/progress.log``.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import time
import tomllib
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from evalnoise import __version__
from evalnoise.components import Components, Estimate, RunTerm, bootstrap, estimate
from evalnoise.data import DataError, describe, load_trials
from evalnoise.power import (
    Design,
    mde,
    naive_false_positive_rate,
    plan,
    resolve,
    tasks_needed,
    variance_terms,
)
from evalnoise.reml import reml
from evalnoise.sources import sha256

COMPONENTS = ("item", "item_arm", "run", "item_run", "within")
# Bump when the unit format or any computation in analyse() changes, so cached units rerun.
SCHEMA = 5
# Pairs whose arms differ on fewer items than this get a reliability note.
MIN_ITEMS_DIFFERING = 10


def load_study(path: Path) -> tuple[Path, dict[str, Any]]:
    path = Path(path)
    try:
        cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DataError(f"{path}: {exc}") from None
    if "profiles" not in cfg or "dataset" not in cfg:
        raise DataError(f"{path}: needs [profiles.*] and [[dataset]] sections")
    ids = [d.get("id") for d in cfg["dataset"]]
    if len(set(ids)) != len(ids) or not all(ids):
        raise DataError(f"{path}: every dataset needs a unique id")
    for d in cfg["dataset"]:
        for key in ("id", "name", "table", "score"):
            if key not in d:
                raise DataError(f"{path}: dataset {d.get('id')!r} missing {key!r}")
    return path.resolve().parent.parent, cfg


def run_study(
    config: Path,
    out: Path,
    profile: str = "quick",
    only: list[str] | None = None,
    force: bool = False,
    trials_dir: Path | None = None,
) -> list[dict[str, Any]]:
    root, cfg = load_study(config)
    if profile not in cfg["profiles"]:
        raise DataError(f"unknown profile {profile!r}; have {sorted(cfg['profiles'])}")
    prof = cfg["profiles"][profile]
    defaults = cfg.get("defaults", {})
    datasets = cfg["dataset"]
    if only:
        unknown = set(only) - {d["id"] for d in datasets}
        if unknown:
            raise DataError(f"unknown dataset id(s): {', '.join(sorted(unknown))}")
        datasets = [d for d in datasets if d["id"] in only]
    tdir = trials_dir or root / cfg.get("trials_dir", "results/trials")
    # Validate inputs before writing anything.
    for d in datasets:
        if not (tdir / f"{d['table']}.csv").is_file():
            raise DataError(f"dataset {d['id']}: table {d['table']}.csv not found in {tdir}")
    units = out / "units"
    units.mkdir(parents=True, exist_ok=True)
    log = out / "progress.log"
    results = []
    for n, d in enumerate(datasets, 1):
        table = tdir / f"{d['table']}.csv"
        key = _unit_key(d, prof, defaults, sha256(table))
        path = units / f"{d['id']}.json"
        if path.is_file() and not force:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if prev.get("key") == key:
                _log(log, f"[{n}/{len(datasets)}] {d['id']}: up to date, skipped")
                results.append(prev)
                continue
        t0 = time.perf_counter()
        res = analyse(load_trials(table, {"score": d["score"]}), d, prof, defaults)
        res["key"] = key
        res["table_sha256"] = sha256(table)
        res["seconds"] = round(time.perf_counter() - t0, 2)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_clean(res), indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        _log(log, f"[{n}/{len(datasets)}] {d['id']}: done in {res['seconds']}s")
        results.append(json.loads(path.read_text(encoding="utf-8")))
    return results


def analyse(
    df: pd.DataFrame, d: dict[str, Any], prof: dict[str, Any], defaults: dict[str, Any]
) -> dict[str, Any]:
    """Everything reported for one dataset."""
    scale = float(d.get("scale", 1.0))
    df = df.assign(score=df["score"] * scale)
    arms = _select_arms(df, d.get("arms", "all"))
    df = df[df["arm"].isin(arms)].reset_index(drop=True)
    pairs = _select_pairs(arms, d.get("pairs", "all"))
    seed = (int(prof.get("seed", 0)) + zlib.crc32(d["id"].encode())) % 2**32
    est = estimate(df, arms=arms, pairs=pairs)
    boot = bootstrap(df, arms=arms, pairs=pairs, draws=int(prof["bootstrap"]), seed=seed)
    try:
        rm = reml(df, arms=arms).to_dict()
    except DataError as exc:
        rm = {"error": str(exc)}
    comps = est.components
    clipped = comps.clipped()
    run_ci = est.run_term.interval()

    alpha = float(d.get("alpha", defaults.get("alpha", 0.05)))
    target_power = float(d.get("power", defaults.get("power", 0.8)))
    grid_tasks = d.get("tasks", defaults.get("tasks", [10, 20, 50, 100, 200]))
    grid_runs = d.get("runs", defaults.get("runs", [1, 2, 4]))
    grid_reps = d.get("repeats", defaults.get("repeats", [1, 3]))
    targets = d.get("targets", defaults.get("targets", []))
    run_identified = math.isfinite(comps.run)
    # The analysis borrows the run variance estimated here, with its degrees of freedom.
    run_df = float(est.run_term.df) if run_identified else math.inf
    by_arm = _run_by_arm(est)
    pair_est = _pairs_with_run_term(est.pairs, pairs, df, comps, run_df)
    planning: dict[str, Any] = {"alpha": alpha, "power": target_power}
    paired_ok = len(arms) >= 2
    if paired_ok:
        planning["run_df"] = run_df
        res_est = resolve(comps, run=None if run_identified else 0.0, run_df=run_df)
        planning["run_assumption"] = "estimated" if run_identified else "zero (not identified)"
        planning["notes"] = list(res_est.notes) + _data_notes(by_arm, pair_est, planning)
        # Reference design: the observed tasks and repeats with one run per arm, which is
        # how the source studies compared arms. Its SE includes the run variance estimated
        # here, as an analyst who knows it from this study would.
        obs = _observed_design(df)
        planning["observed_design"] = obs
        ref = Design(obs["tasks"], 1, obs["repeats"], True)
        planning["reference_design"] = {"tasks": ref.tasks, "runs": 1, "repeats": ref.repeats}
        planning["reference_mde"] = mde(res_est, ref, alpha=alpha, power=target_power)
        planning["reference_mde_bootstrap_ci"] = _mde_boot_ci(
            boot.samples, comps, ref, alpha, target_power, run_identified, run_df
        )
        v_items, v_run = variance_terms(res_est, ref)
        planning["reference_se"] = math.sqrt(v_items + v_run)
        planning["reference_se_items_only"] = math.sqrt(v_items)
        if run_identified:
            planning["run_share_of_variance"] = (
                v_run / (v_items + v_run) if v_items + v_run else 0.0
            )
            planning["reference_mde_run_ci"] = [
                mde(resolve(comps, run=v, run_df=run_df), ref, alpha=alpha, power=target_power)
                for v in run_ci
            ]
            planning["naive_fpr"] = naive_false_positive_rate(res_est, ref, alpha=alpha)
            planning["naive_fpr_run_ci"] = [
                naive_false_positive_rate(resolve(comps, run=v), ref, alpha=alpha) for v in run_ci
            ]
        planning["grid"] = plan(
            res_est, grid_tasks, grid_runs, grid_reps, alpha=alpha, power=target_power
        )
        planning["targets"] = {
            str(tg): [
                {
                    "runs": r,
                    "repeats": k,
                    "tasks": tasks_needed(
                        res_est, float(tg), runs=r, repeats=k, alpha=alpha, power=target_power
                    ),
                }
                for r, k in itertools.product(grid_runs, grid_reps)
            ]
            for tg in targets
        }
        planning["reference_mde_unpaired"] = mde(
            resolve(comps, run=None if run_identified else 0.0, paired=False, run_df=run_df),
            Design(ref.tasks, 1, ref.repeats, False),
            alpha=alpha,
            power=target_power,
        )

    return {
        "id": d["id"],
        "name": d["name"],
        "table": d["table"],
        "score": d["score"],
        "unit": d.get("unit", ""),
        "digits": int(d.get("digits", 1)),
        "scale": scale,
        "note": d.get("note", ""),
        "evalnoise": __version__,
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arms": arms,
        "pairs": [list(p) for p in pairs],
        "counts": describe(df),
        "components": comps.to_dict(),
        "components_clipped": clipped.to_dict(),
        "bootstrap": {
            "draws": boot.draws,
            "level": boot.level,
            "components": {k: list(v) for k, v in boot.components.items()},
            "pairs": {k: {f: list(v) for f, v in p.items()} for k, p in boot.pairs.items()},
        },
        "run_interval": list(run_ci),
        "run_term": {
            "ss": est.run_term.ss,
            "df": est.run_term.df,
            "k": est.run_term.k,
            "df_res": est.run_term.df_res,
        },
        "reml": rm,
        "shares": _shares(clipped),
        "per_arm": est.per_arm,
        "run_by_arm": by_arm,
        "pair_estimates": pair_est,
        "planning": planning,
    }


def _pairs_with_run_term(
    pair_est: dict[str, dict[str, float]],
    pairs: list[tuple[str, str]],
    df: pd.DataFrame,
    comps: Components,
    run_df: float,
) -> dict[str, dict[str, float]]:
    """Add t-tests of each pair's difference: over clusters, and with the run variance.

    The item-level part uses the cluster-robust SE with clusters - 1 df. Where the run
    variance is identified, each arm adds run / R_eff, with R_eff its trials divided by
    (items x median repeats per cell), so a half-finished replicate run counts as half a
    run; the df are Satterthwaite's, with ``run_df`` for the run term.
    """
    out = {k: dict(v) for k, v in pair_est.items()}
    cells = df.groupby(["arm", "run", "item"]).size()
    eff = {}
    for arm, sub in df.groupby("arm"):
        reps = float(cells.loc[arm].median())
        eff[arm] = len(sub) / (sub["item"].nunique() * reps)
    for a, b in pairs:
        p = out[f"{a} - {b}"]
        se_i, df_i = p["se_clusters"], p["clusters"] - 1
        p["p_items"] = _t_p(p["difference"], [(se_i**2, df_i)])
        if not math.isfinite(comps.run):
            continue
        v_run = max(comps.run, 0.0) * (1 / eff[a] + 1 / eff[b])
        terms = [(se_i**2, df_i), (v_run, run_df)]
        p["runs_eff"] = [eff[a], eff[b]]
        p["se_with_run"] = math.sqrt(se_i**2 + v_run)
        p["df_with_run"] = _satterthwaite(terms)
        p["p_with_run"] = _t_p(p["difference"], terms)
    return out


def _satterthwaite(terms: list[tuple[float, float]]) -> float:
    denom = sum(v * v / k for v, k in terms if v > 0)
    total = sum(v for v, _ in terms)
    return math.inf if denom == 0 else total * total / denom


def _t_p(diff: float, terms: list[tuple[float, float]]) -> float:
    """Two-sided p-value of diff / sqrt(sum of variances), Satterthwaite t."""
    se = math.sqrt(sum(v for v, _ in terms))
    if se == 0:
        return math.nan
    return float(2 * stats.t.sf(abs(diff) / se, _satterthwaite(terms)))


def _run_by_arm(est: Estimate) -> dict[str, Any]:
    """Run and item x run estimates per replicated arm, leave-one-arm-out run estimates,
    and Bartlett's test that the arms share one item x run (residual) variance."""
    terms = est.run_terms
    if not terms:
        return {}
    within = est.components.within
    arms: dict[str, Any] = {}
    for arm, t in terms.items():
        s2 = t.rss / t.df_res if t.df_res >= 1 else math.nan
        arms[arm] = {
            "run": t.variance(),
            "run_interval": list(t.interval()),
            "run_df": t.df,
            "item_run": s2 - within / t.n_harmonic if math.isfinite(within) else s2,
            "residual_df": t.df_res,
        }
    out: dict[str, Any] = {"arms": arms}
    if len(terms) >= 2:
        loo = {}
        for arm in terms:
            rest = RunTerm.pool(t for a, t in terms.items() if a != arm)
            loo[arm] = {"run": rest.variance(), "run_interval": list(rest.interval())}
        out["leave_one_out"] = loo
        out["residual_homogeneity"] = _bartlett(
            [(t.rss / t.df_res, t.df_res) for t in terms.values() if t.df_res >= 1]
        )
    return out


def _bartlett(groups: list[tuple[float, int]]) -> dict[str, float]:
    """Bartlett's test of equal variances from (variance, df) pairs."""
    v = np.array([g[0] for g in groups], dtype=float)
    nu = np.array([g[1] for g in groups], dtype=float)
    n, k = nu.sum(), len(nu)
    if k < 2 or np.any(v <= 0):
        return {"statistic": math.nan, "df": k - 1, "p": math.nan}
    pooled = float(nu @ v / n)
    corr = 1 + (np.sum(1 / nu) - 1 / n) / (3 * (k - 1))
    stat = float((n * math.log(pooled) - nu @ np.log(v)) / corr)
    return {"statistic": stat, "df": k - 1, "p": float(stats.chi2.sf(stat, k - 1))}


def _data_notes(
    by_arm: dict[str, Any], pair_est: dict[str, dict[str, float]], planning: dict[str, Any]
) -> list[str]:
    """Warnings about assumptions the data contradict."""
    notes = []
    hom = by_arm.get("residual_homogeneity")
    if hom and hom["p"] < 0.05:
        sds = ", ".join(
            f"{a} {math.sqrt(max(x['item_run'], 0)):.3g}" for a, x in by_arm["arms"].items()
        )
        notes.append(
            f"the replicated arms do not share one item x run variance (Bartlett p = "
            f"{hom['p']:.2g}; SD by arm: {sds}): pooled components describe an average arm"
        )
    ratios = [
        (p["se_clusters"] / p["se_items"]) ** 2
        for p in pair_est.values()
        if p["clusters"] < p["items"] and p["se_items"] > 0
    ]
    if ratios:
        deff = float(np.median(ratios))
        planning["design_effect"] = deff
        if deff > 1.05:
            notes.append(
                f"items are clustered (median design effect {deff:.2f} over pairs): the "
                f"planner treats items as independent, so its task counts are about "
                f"{deff:.2f}x too small"
            )
    few = {k: p["items_differing"] for k, p in pair_est.items()}
    few = {k: n for k, n in few.items() if n < MIN_ITEMS_DIFFERING}
    if few:
        planning["few_items_differing"] = few
        listed = "; ".join(f"{k}: {n}" for k, n in few.items())
        notes.append(
            f"arms differ on fewer than {MIN_ITEMS_DIFFERING} items ({listed}): SEs, MDEs and "
            "their intervals rest on those few items and are unreliable"
        )
    return notes


def _select_arms(df: pd.DataFrame, spec: Any) -> list[str]:
    have = sorted(df["arm"].unique())
    if spec == "all":
        return have
    if spec == "replicated":
        runs = df.groupby("arm")["run"].nunique()
        arms = sorted(runs[runs >= 2].index)
        if not arms:
            raise DataError("no arm has two or more runs")
        return arms
    if isinstance(spec, list):
        missing = sorted(set(spec) - set(have))
        if missing:
            raise DataError(f"arm(s) not in table: {', '.join(missing)}")
        return list(spec)
    raise DataError(f"arms must be 'all', 'replicated' or a list, got {spec!r}")


def _select_pairs(arms: list[str], spec: Any) -> list[tuple[str, str]]:
    if spec == "all":
        return list(itertools.combinations(arms, 2))
    if spec == "none":
        return []
    out = []
    for p in spec:
        if len(p) != 2 or p[0] not in arms or p[1] not in arms:
            raise DataError(f"pair {p!r} must name two selected arms")
        out.append((p[0], p[1]))
    return out


def _observed_design(df: pd.DataFrame) -> dict[str, int]:
    tasks = int(df.groupby("arm")["item"].nunique().median())
    runs = int(df.groupby("arm")["run"].nunique().median())
    reps = int(df.groupby(["arm", "run", "item"]).size().median())
    return {"tasks": max(tasks, 2), "runs": max(runs, 1), "repeats": max(reps, 1)}


def _mde_boot_ci(
    samples: dict[str, np.ndarray],
    comps: Components,
    d: Design,
    alpha: float,
    power: float,
    run_identified: bool,
    run_df: float,
) -> list[float]:
    """Percentile interval of the MDE over bootstrap draws (run variance held at its estimate)."""
    vals = []
    n = len(samples["item"])
    for j in range(n):
        c = Components(
            item=float(samples["item"][j]),
            item_arm=float(samples["item_arm"][j]),
            run=comps.run,
            item_run=float(samples["item_run"][j]) if len(samples["item_run"]) else math.nan,
            within=float(samples["within"][j]) if len(samples["within"]) else math.nan,
            absorbed=comps.absorbed,
        )
        r = resolve(c, run=None if run_identified else 0.0, run_df=run_df)
        vals.append(mde(r, d, alpha=alpha, power=power))
    lo, hi = np.quantile(np.asarray(vals), [0.025, 0.975])
    return [float(lo), float(hi)]


def _shares(c: Components) -> dict[str, float]:
    """Share of one trial's variance (within an arm) taken by each identified component."""
    parts = {k: getattr(c, k) for k in COMPONENTS}
    finite = {k: v for k, v in parts.items() if math.isfinite(v)}
    total = sum(finite.values())
    return {k: (v / total if total > 0 else math.nan) for k, v in finite.items()}


def _unit_key(
    d: dict[str, Any], prof: dict[str, Any], defaults: dict[str, Any], digest: str
) -> str:
    blob = json.dumps(
        {"d": d, "p": prof, "defaults": defaults, "t": digest, "v": __version__, "s": SCHEMA},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _log(path: Path, msg: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {msg}\n")


def _clean(x: Any) -> Any:
    """JSON-safe: numpy scalars to Python, non-finite floats to None."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, np.integer):
        return int(x)
    return x
