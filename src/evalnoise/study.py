"""The variance-components study over the committed trial tables (configs/study.toml).

Each dataset is one unit: estimates, bootstrap intervals, REML cross-check and planning
tables are written to ``<out>/units/<id>.json`` atomically. A unit is skipped on rerun when
its key (config entry, profile and input-table hash) is unchanged, so an interrupted study
resumes where it stopped. Progress goes to ``<out>/progress.log``.
"""

from __future__ import annotations

import dataclasses
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
from evalnoise.data import DataError, describe, load_trials, read_table
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
SCHEMA = 8
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
        # Both name files under the output and trials directories.
        for key in ("id", "table"):
            v = d[key]
            if not isinstance(v, str) or not v or not all(ch.isalnum() or ch in "-_" for ch in v):
                raise DataError(f"{path}: dataset {key} {v!r} must be alphanumeric, - or _")
        b = d.get("bounds")
        if b is not None and not (
            isinstance(b, list)
            and len(b) == 2
            and all(isinstance(x, (int, float)) for x in b)
            and b[0] < b[1]
        ):
            raise DataError(f"{path}: dataset {d['id']!r} bounds must be [low, high], low < high")
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
        trials = load_trials(table, {"score": d["score"]})
        if "family" in d:
            trials = _with_families(trials, table, d["family"])
        res = analyse(trials, d, prof, defaults)
        res["key"] = key
        res["table_sha256"] = sha256(table)
        res["seconds"] = round(time.perf_counter() - t0, 2)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_clean(res), indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        _log(log, f"[{n}/{len(datasets)}] {d['id']}: done in {res['seconds']}s")
        results.append(json.loads(path.read_text(encoding="utf-8")))
    return results


def _with_families(df: pd.DataFrame, table: Path, column: str) -> pd.DataFrame:
    """Add a ``family`` column (a grouping of items above the cluster) from the raw table."""
    raw = read_table(table)
    if column not in raw.columns:
        raise DataError(f"{table.name}: family column {column!r} not found")
    fam = raw.groupby("item")[column].agg(lambda s: s.unique().tolist())
    split = fam[fam.map(len) > 1]
    if len(split):
        raise DataError(f"{table.name}: item {split.index[0]!r} is in more than one family")
    return df.assign(family=df["item"].map(fam.str[0]))


def analyse(
    df: pd.DataFrame, d: dict[str, Any], prof: dict[str, Any], defaults: dict[str, Any]
) -> dict[str, Any]:
    """Everything reported for one dataset. An optional ``family`` column groups items above
    the cluster level: pairs then also get family-clustered SEs, and run shifts are broken
    down by family."""
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
    # Scores bounded to [low, high] (after scaling) cannot vary by more than (range / 2)^2.
    max_var = math.inf
    # Pass/fail scores (every score at a bound): MDEs use the variance at the shifted rate.
    rate_kw: dict[str, float] = {}
    if "bounds" in d:
        low, high = d["bounds"]
        if df["score"].min() < low or df["score"].max() > high:
            raise DataError(f"dataset {d['id']}: scores fall outside bounds {d['bounds']}")
        max_var = ((high - low) / 2) ** 2
        rate = (float(df["score"].mean()) - low) / (high - low)
        if df["score"].isin([low, high]).all() and 0 < rate < 1:
            rate_kw = {"pass_rate": rate, "pass_score": float(high - low)}
    run_ci = est.run_term.interval(max_var=max_var)

    alpha = float(d.get("alpha", defaults.get("alpha", 0.05)))
    target_power = float(d.get("power", defaults.get("power", 0.8)))
    grid_tasks = d.get("tasks", defaults.get("tasks", [10, 20, 50, 100, 200]))
    grid_runs = d.get("runs", defaults.get("runs", [1, 2, 4]))
    grid_reps = d.get("repeats", defaults.get("repeats", [1, 3]))
    targets = d.get("targets", defaults.get("targets", []))
    run_identified = math.isfinite(comps.run)
    # The analysis borrows the run variance estimated here, with its degrees of freedom.
    run_df = float(est.run_term.df) if run_identified else math.inf
    by_arm = _run_by_arm(est, max_var)
    pair_est = _pairs_with_run_term(est.pairs, pairs, df, comps, run_df)
    if "family" in df.columns:
        by_arm["shifts"] = _run_shifts(df)
        fam = estimate(df.assign(cluster=df["family"]), arms=arms, pairs=pairs).pairs
        for k, p in pair_est.items():
            p["families"] = fam[k]["clusters"]
            p["se_families"] = fam[k]["se_clusters"]
    # The pooled run variance is an average over arms that may differ: redo the run-aware
    # tests with the run variance re-estimated without each replicated arm in turn.
    for left_out, x in by_arm.get("leave_one_out", {}).items():
        if not math.isfinite(x["run"]):
            continue
        alt = _pairs_with_run_term(
            est.pairs, pairs, df, dataclasses.replace(comps, run=x["run"]), float(x["run_df"])
        )
        for k, p in pair_est.items():
            p.setdefault("p_with_run_without", {})[left_out] = alt[k]["p_with_run"]
    planning: dict[str, Any] = {"alpha": alpha, "power": target_power}
    paired_ok = len(arms) >= 2
    if paired_ok:
        planning["run_df"] = run_df
        res_est = resolve(comps, run=None if run_identified else 0.0, run_df=run_df, **rate_kw)
        planning["run_assumption"] = "estimated" if run_identified else "zero (not identified)"
        planning["notes"] = list(res_est.notes) + _data_notes(by_arm, pair_est, planning)
        # Task counts count a cluster's items as worth 1 / design effect independent ones.
        deff = max(planning.get("design_effect", 1.0), 1.0)
        res_tasks = dataclasses.replace(res_est, design_effect=deff)
        planning["targets_design_effect"] = deff
        # Reference design: the observed tasks and repeats with one run per arm, which is
        # how the source studies compared arms. Its SE includes the run variance estimated
        # here, as an analyst who knows it from this study would.
        obs = _observed_design(df)
        planning["observed_design"] = obs
        ref = Design(obs["tasks"], 1, obs["repeats"], True)
        planning["reference_design"] = {"tasks": ref.tasks, "runs": 1, "repeats": ref.repeats}
        planning["reference_mde"] = mde(res_est, ref, alpha=alpha, power=target_power)
        planning["reference_mde_bootstrap_ci"] = _mde_boot_ci(
            boot.samples, comps, ref, alpha, target_power, run_identified, run_df, rate_kw
        )
        v_items, v_run = variance_terms(res_est, ref)
        planning["reference_se"] = math.sqrt(v_items + v_run)
        planning["reference_se_items_only"] = math.sqrt(v_items)
        if run_identified:
            planning["run_share_of_variance"] = (
                v_run / (v_items + v_run) if v_items + v_run else 0.0
            )
            # A degenerate run interval (nan ends) leaves these ends undefined.
            planning["reference_mde_run_ci"] = [
                mde(
                    resolve(comps, run=v, run_df=run_df, **rate_kw),
                    ref,
                    alpha=alpha,
                    power=target_power,
                )
                if math.isfinite(v)
                else math.nan
                for v in run_ci
            ]
            planning["naive_fpr"] = naive_false_positive_rate(res_est, ref, alpha=alpha)
            planning["naive_fpr_run_ci"] = [
                naive_false_positive_rate(resolve(comps, run=v), ref, alpha=alpha)
                if math.isfinite(v)
                else math.nan
                for v in run_ci
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
                        res_tasks, float(tg), runs=r, repeats=k, alpha=alpha, power=target_power
                    ),
                }
                for r, k in itertools.product(grid_runs, grid_reps)
            ]
            for tg in targets
        }
        planning["reference_mde_unpaired"] = mde(
            resolve(
                comps,
                run=None if run_identified else 0.0,
                paired=False,
                run_df=run_df,
                **rate_kw,
            ),
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
    variance is identified, each arm adds run / R with R its number of runs: the
    run-adjusted item means average every run's shock equally, so a partial replicate run
    counts as a whole run. The df are Satterthwaite's, with ``run_df`` for the run term.
    """
    out = {k: dict(v) for k, v in pair_est.items()}
    n_runs = df.groupby("arm")["run"].nunique()
    for a, b in pairs:
        p = out[f"{a} - {b}"]
        se_i, df_i = p["se_clusters"], p["clusters"] - 1
        p["p_items"] = _t_p(p["difference"], [(se_i**2, df_i)])
        if not math.isfinite(comps.run):
            continue
        v_run = max(comps.run, 0.0) * (1 / n_runs[a] + 1 / n_runs[b])
        terms = [(se_i**2, df_i), (v_run, run_df)]
        p["runs"] = [int(n_runs[a]), int(n_runs[b])]
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


def _run_by_arm(est: Estimate, max_var: float = math.inf) -> dict[str, Any]:
    """Run and item x run estimates per replicated arm, leave-one-arm-out run estimates,
    and Bartlett's and a Brown-Forsythe test that the arms share one item x run (residual)
    variance."""
    terms = est.run_terms
    if not terms:
        return {}
    within = est.components.within
    arms: dict[str, Any] = {}
    for arm, t in terms.items():
        s2 = t.rss / t.df_res if t.df_res >= 1 else math.nan
        arms[arm] = {
            "run": t.variance(),
            "run_interval": list(t.interval(max_var=max_var)),
            "run_df": t.df,
            "item_run": s2 - within / t.n_harmonic if math.isfinite(within) else s2,
            "residual_df": t.df_res,
        }
    out: dict[str, Any] = {"arms": arms}
    if len(terms) >= 2:
        loo = {}
        for arm in terms:
            rest = RunTerm.pool(t for a, t in terms.items() if a != arm)
            loo[arm] = {
                "run": rest.variance(),
                "run_interval": list(rest.interval(max_var=max_var)),
                "run_df": rest.df,
            }
        out["leave_one_out"] = loo
        out["residual_homogeneity"] = _bartlett(
            [(t.rss / t.df_res, t.df_res) for t in terms.values() if t.df_res >= 1]
        )
        out["residual_homogeneity_bf"] = _brown_forsythe(list(terms.values()))
    return out


def _run_shifts(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Mean change between each two runs of an arm over the items both cover: overall,
    median over items, and by family (a shift shared by every trial is equal across
    families; family-specific shifts shrink with more families, not more items)."""
    out = []
    cells = df.groupby(["arm", "run", "item"])["score"].mean()
    fam = df.groupby("item")["family"].first()
    for arm in sorted(df["arm"].unique()):
        by_run = cells.loc[arm].unstack("run")
        for r1, r2 in itertools.combinations(sorted(by_run.columns), 2):
            both = by_run[[r1, r2]].dropna()
            d = both[r2] - both[r1]
            if len(d) < 2:
                continue
            by_fam = d.groupby(fam.loc[d.index]).mean()
            out.append(
                {
                    "arm": arm,
                    "runs": [r1, r2],
                    "items": len(d),
                    "run_means": [float(both[r1].mean()), float(both[r2].mean())],
                    "mean": float(d.mean()),
                    "median": float(d.median()),
                    "by_family": {str(f): float(v) for f, v in by_fam.items()},
                }
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


def _brown_forsythe(terms: list[RunTerm]) -> dict[str, Any]:
    """Brown-Forsythe test of equal residual variances across arms, with items as units.

    Each arm's residuals are scaled by ``sqrt(cells / df_res)`` (a residual's variance is
    about the residual variance times ``df_res / cells``) and centred at the arm's median;
    each item's mean absolute deviation is one observation, and a one-way ANOVA compares
    the arms. Items, not cells, are the units because an item's residuals within an arm
    are dependent (with two runs they are equal and opposite), which makes a cell-level
    test far too liberal. Items in only one run of an arm have zero residuals there and
    are left out.
    """
    groups = []
    for t in terms:
        if t.df_res < 1 or len(t.residuals) == 0:
            continue
        e = t.residuals * math.sqrt(len(t.residuals) / t.df_res)
        _, idx, n_cells = np.unique(t.residual_items, return_inverse=True, return_counts=True)
        z = np.bincount(idx, weights=np.abs(e - np.median(e))) / n_cells
        z = z[n_cells >= 2]
        if len(z) >= 2:
            groups.append(z)
    k = len(groups)
    n = sum(len(g) for g in groups)
    if k < 2 or all(np.ptp(g) == 0 for g in groups):
        return {"statistic": math.nan, "df": [k - 1, n - k], "p": math.nan}
    res = stats.f_oneway(*groups)
    return {"statistic": float(res.statistic), "df": [k - 1, n - k], "p": float(res.pvalue)}


def _data_notes(
    by_arm: dict[str, Any], pair_est: dict[str, dict[str, float]], planning: dict[str, Any]
) -> list[str]:
    """Warnings about assumptions the data contradict."""
    notes = []
    hom = by_arm.get("residual_homogeneity_bf")
    if hom and hom["p"] < 0.05:
        sds = ", ".join(
            f"{a} {math.sqrt(max(x['item_run'], 0)):.3g}" for a, x in by_arm["arms"].items()
        )
        notes.append(
            f"the replicated arms do not share one item x run variance (Brown-Forsythe p = "
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
                "tasks-needed counts multiply the item-level variance by it; the grid and "
                "reference-design MDEs treat items as independent"
            )
    fam = [
        (p["se_families"] / p["se_items"]) ** 2
        for p in pair_est.values()
        if "se_families" in p and p["se_items"] > 0 and math.isfinite(p["se_families"])
    ]
    if fam:
        deff = float(np.median(fam))
        n_fam = min(p["families"] for p in pair_est.values())
        planning["design_effect_families"] = deff
        if deff > 1.05:
            notes.append(
                f"items are also clustered by family (median design effect {deff:.2f} over "
                f"pairs, from only {n_fam} families, so rough): counting items as "
                "independent, or only clusters as dependent, overstates the information"
            )
    few = {k: p["items_differing"] for k, p in pair_est.items()}
    few = {k: n for k, n in few.items() if n < MIN_ITEMS_DIFFERING}
    if few:
        planning["few_items_differing"] = few
        listed = "; ".join(f"{k}: {n}" for k, n in few.items())
        notes.append(
            f"arms differ on fewer than {MIN_ITEMS_DIFFERING} items ({listed}): those pairs' "
            "SEs, MDEs and intervals rest on those few items and are unreliable"
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
    rate_kw: dict[str, float],
) -> list[float]:
    """Percentile interval of the MDE over bootstrap draws (run variance held at its estimate)."""
    vals = []
    n = len(samples["item"])
    for j in range(n):
        item_run, within = float(samples["item_run"][j]), float(samples["within"][j])
        # A draw without the few replicated items folds that noise into item_arm.
        noise = {"item_run": item_run, "within": within}
        c = Components(
            item=float(samples["item"][j]),
            item_arm=float(samples["item_arm"][j]),
            run=comps.run,
            item_run=item_run,
            within=within,
            absorbed=comps.absorbed
            | {k: "item_arm" for k, v in noise.items() if not math.isfinite(v)},
        )
        r = resolve(c, run=None if run_identified else 0.0, run_df=run_df, **rate_kw)
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
