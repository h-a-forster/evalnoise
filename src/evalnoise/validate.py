"""Monte Carlo checks that the planning formulas and intervals do what they claim.

Each check runs in shards; every finished shard is written to
``<out>/units/<check>/shard-<k>.json`` and skipped on rerun when its key is unchanged, and
the shards are then pooled into ``<out>/units/<check>.json``. Checks:

- ``power-*``: data with no run effect, analysed by a paired t-test over items. Rejection
  rate at effect 0 should be alpha; at the planned MDE it should be the target power.
- ``runs-*``: data with a run effect and several runs per arm, analysed with the moment
  estimates and the Satterthwaite t-test the planner assumes.
- ``naive-*``: one run per arm with a run effect, analysed by the paired t-test that ignores
  runs; the rejection rate at effect 0 should match :func:`naive_false_positive_rate`.
- ``binary-*``: pass/fail data from a logistic model, planned from a large pilot on the
  probability scale, analysed by the paired t-test (checks the linear approximation),
  including near the ceiling with the effect in either direction.
- ``borrowed-*``: one run per arm, with the run variance borrowed from a small pilot (its
  own few run df), analysed by the Satterthwaite t-test the study's MDEs assume.
- ``coverage-*``: coverage of the bootstrap and run-variance (MLS) intervals.
- ``pairs-*``: an mm-arena-like layout (setups with 2 to 4 runs, one partial replicate
  run, item x run variances differing sixfold, items in clusters of two): size of the
  study's run-aware pair test and coverage of the pooled run-variance interval.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from evalnoise import __version__
from evalnoise.components import Components, bootstrap, estimate
from evalnoise.power import Design, mde, naive_false_positive_rate, resolve, se_difference
from evalnoise.power import _df as satterthwaite_df
from evalnoise.simulate import simulate

# sims: per check (power, naive); run_sims: runs checks; binary_sims; coverage_sims with
# `boot` bootstrap draws each. Each check is split into `shards` resumable shards.
PROFILES: dict[str, dict[str, int]] = {
    "quick": {
        "sims": 2000, "run_sims": 400, "binary_sims": 500, "coverage_sims": 120, "boot": 200,
        "shards": 1, "seed": 7,
    },
    "full": {
        "sims": 20000, "run_sims": 4000, "binary_sims": 5000, "coverage_sims": 1000,
        "boot": 400, "shards": 20, "seed": 7,
    },
}  # fmt: skip
# Bump when a check's computation changes, so cached shards rerun.
SCHEMA = 5


@dataclass(frozen=True)
class Check:
    name: str
    kind: str
    comps: Components
    design: Design
    params: dict[str, Any] = field(default_factory=dict)


BASE = Components(item=400.0, item_arm=60.0, run=0.0, item_run=0.0, within=300.0)
RUNNY = Components(item=400.0, item_arm=60.0, run=20.0, item_run=100.0, within=0.0)

CHECKS = [
    Check("power-t20-k1", "power", BASE, Design(20, 1, 1)),
    Check("power-t50-k3", "power", BASE, Design(50, 1, 3)),
    Check("power-t10-k5", "power", BASE, Design(10, 1, 5)),
    Check("runs-t60-r3", "runs", RUNNY, Design(60, 3, 1)),
    Check("runs-t60-r6", "runs", RUNNY, Design(60, 6, 1)),
    Check("naive-t120-r1", "naive", RUNNY, Design(120, 1, 1)),
    Check("naive-t30-r1", "naive", RUNNY, Design(30, 1, 1)),
    Check(
        "binary-t50-k3",
        "binary",
        Components(item=2.0, item_arm=0.3, run=0.0, item_run=0.0, within=0.0),
        Design(50, 1, 3),
        {"mean": 1.0},
    ),
    Check(
        "binary-t30-k1",
        "binary",
        Components(item=3.0, item_arm=0.5, run=0.0, item_run=0.0, within=0.0),
        Design(30, 1, 1),
        {"mean": 0.5},
    ),
    # About 90% pass (logit mean 2.97 with logit variance 2.3): gains vs losses.
    Check(
        "binary-p90-t50-k3-up",
        "binary",
        Components(item=2.0, item_arm=0.3, run=0.0, item_run=0.0, within=0.0),
        Design(50, 1, 3),
        {"mean": 2.97, "direction": 1},
    ),
    Check(
        "binary-p90-t50-k3-down",
        "binary",
        Components(item=2.0, item_arm=0.3, run=0.0, item_run=0.0, within=0.0),
        Design(50, 1, 3),
        {"mean": 2.97, "direction": -1},
    ),
    # Pilot of 7 arms x 2 runs (7 run df, as mm-arena's pooled run term), then a 120-task,
    # one-run-per-arm comparison.
    Check(
        "borrowed-t120-r1",
        "borrowed",
        RUNNY,
        Design(120, 1, 1),
        {"pilot_arms": 7, "pilot_runs": 2},
    ),
    Check("coverage-t40-a2-k3", "coverage", BASE, Design(40, 1, 3)),
    Check("coverage-t60-a3-r3", "coverage", RUNNY, Design(60, 3, 1), {"arms": 3}),
    # Four setups as in mm-arena-replicated: runs 2, 2, 2, 4 (arm0's second run covers half
    # the items), item x run variance per setup; no item effect (it cancels in pairs).
    Check(
        "pairs-t120-mm",
        "pairs",
        dataclasses.replace(RUNNY, item=0.0),
        Design(120, 2, 1),
        {"runs": [2, 2, 2, 4], "item_run": [50.0, 100.0, 150.0, 300.0], "partial": 0.5},
    ),
]


# A check is (prepare, count, sims key): prepare(check, rng) -> context with "nominal"
# rates (deterministic per check), count(check, context, sims, rng, profile) -> hits.
Prepare = Callable[[Check, np.random.Generator], dict[str, Any]]
Count = Callable[[Check, dict[str, Any], int, np.random.Generator, dict[str, int]], dict[str, int]]


def run_validation(
    out: Path, profile: str = "quick", only: list[str] | None = None, force: bool = False
) -> list[dict[str, Any]]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; have {sorted(PROFILES)}")
    prof = PROFILES[profile]
    checks = CHECKS
    if only:
        unknown = set(only) - {c.name for c in CHECKS}
        if unknown:
            raise ValueError(f"unknown check(s): {', '.join(sorted(unknown))}")
        checks = [c for c in CHECKS if c.name in only]
    units = out / "units"
    units.mkdir(parents=True, exist_ok=True)
    results = []
    for n, chk in enumerate(checks, 1):
        prepare, count, sims_key = RUNNERS[chk.kind]
        key = hashlib.sha256(
            json.dumps([repr(chk), prof, __version__, SCHEMA], sort_keys=True).encode()
        ).hexdigest()[:16]
        base_seed = (prof["seed"] + zlib.crc32(chk.name.encode())) % 2**32
        t0 = time.perf_counter()
        ctx = prepare(chk, np.random.default_rng(base_seed))
        shards = prof["shards"]
        total = prof[sims_key]
        sizes = [total // shards + (1 if k < total % shards else 0) for k in range(shards)]
        shard_dir = units / chk.name
        shard_dir.mkdir(exist_ok=True)
        hits: dict[str, int] = {}
        done = 0
        for k, size in enumerate(sizes):
            spath = shard_dir / f"shard-{k}.json"
            rec = None
            if spath.is_file() and not force:
                prev = json.loads(spath.read_text(encoding="utf-8"))
                if prev.get("key") == key:
                    rec = prev
            if rec is None:
                rng = np.random.default_rng([base_seed, k])
                rec = {"key": key, "sims": size, "hits": count(chk, ctx, size, rng, prof)}
                tmp = spath.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(rec) + "\n", encoding="utf-8")
                os.replace(tmp, spath)
                _log(out, f"[{n}/{len(checks)}] {chk.name}: shard {k + 1}/{shards} done")
            for q, h in rec["hits"].items():
                hits[q] = hits.get(q, 0) + int(h)
            done += int(rec["sims"])
        rates = {
            q: {"rate": h / done, "mc95": _mc_interval(h, done), "nominal": ctx["nominal"][q]}
            for q, h in hits.items()
        }
        res = {
            "name": chk.name,
            "kind": chk.kind,
            "key": key,
            "seed": base_seed,
            "sims": done,
            "design": vars(chk.design),
            "components": chk.comps.to_dict(),
            "context": {k: v for k, v in ctx.items() if k != "nominal"},
            "rates": rates,
            "seconds": round(time.perf_counter() - t0, 2),
        }
        path = units / f"{chk.name}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        _log(out, f"[{n}/{len(checks)}] {chk.name}: pooled {done} sims")
        results.append(res)
    return results


def _mc_interval(k: int, n: int) -> list[float]:
    """Exact (Clopper-Pearson) 95% interval for a Monte Carlo rate."""
    lo = stats.beta.ppf(0.025, k, n - k + 1) if k > 0 else 0.0
    hi = stats.beta.ppf(0.975, k + 1, n - k) if k < n else 1.0
    return [float(lo), float(hi)]


def _paired_t_reject(d_items: np.ndarray, alpha: float) -> np.ndarray:
    """Two-sided paired t-test over items; ``d_items`` is (sims, tasks)."""
    t = d_items.shape[1]
    mean = d_items.mean(axis=1)
    se = d_items.std(axis=1, ddof=1) / math.sqrt(t)
    tc = stats.t.ppf(1 - alpha / 2, t - 1)
    return np.abs(mean) > tc * se


def _item_differences(
    c: Components, d: Design, effect: float, sims: int, rng: np.random.Generator
) -> np.ndarray:
    """Per-item mean differences (arm 1 - arm 0) for ``sims`` Gaussian experiments."""
    t, r, k = d.tasks, d.runs, d.repeats
    v = rng.normal(0, math.sqrt(c.item_arm), (sims, 2, t))
    w = rng.normal(0, math.sqrt(c.run), (sims, 2, 1, r))
    g = rng.normal(0, math.sqrt(c.item_run), (sims, 2, t, r))
    e = rng.normal(0, math.sqrt(c.within), (sims, 2, t, r, k)).mean(axis=4)
    y = v + (w + g + e).mean(axis=3)  # item means over runs, per arm
    y[:, 1, :] += effect
    return y[:, 1, :] - y[:, 0, :]  # item main effects cancel in a paired design


# --------------------------------------------------------------------------- power, naive


def _prep_power(chk: Check, rng: np.random.Generator) -> dict[str, Any]:
    # No pilot: any run variance is estimated from the experiment's own runs.
    target = mde(resolve(chk.comps, run_df=0.0), chk.design)
    return {"mde": target, "nominal": {"null": 0.05, "at_mde": 0.8}}


def _count_power(chk, ctx, sims, rng, prof) -> dict[str, int]:  # type: ignore[no-untyped-def]
    out = {}
    for q, eff in (("null", 0.0), ("at_mde", ctx["mde"])):
        d = _item_differences(chk.comps, chk.design, eff, sims, rng)
        out[q] = int(_paired_t_reject(d, 0.05).sum())
    return out


def _prep_naive(chk: Check, rng: np.random.Generator) -> dict[str, Any]:
    return {"nominal": {"null": naive_false_positive_rate(resolve(chk.comps), chk.design)}}


def _count_naive(chk, ctx, sims, rng, prof) -> dict[str, int]:  # type: ignore[no-untyped-def]
    d = _item_differences(chk.comps, chk.design, 0.0, sims, rng)
    return {"null": int(_paired_t_reject(d, 0.05).sum())}


# --------------------------------------------------------------------------- runs


def _count_runs(chk, ctx, sims, rng, prof) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Full pipeline: estimate components from each experiment, then a Satterthwaite t-test."""
    d = chk.design
    out = {}
    for q, eff in (("null", 0.0), ("at_mde", ctx["mde"])):
        rej = 0
        for _ in range(sims):
            df = simulate(
                chk.comps, tasks=d.tasks, runs=d.runs, repeats=d.repeats, effect=eff, seed=rng
            )
            est = estimate(df)
            diff = est.arm_means["arm1"] - est.arm_means["arm0"]
            r_hat = resolve(est.components, run_df=0.0)
            dof = satterthwaite_df(r_hat, d)
            tc = stats.t.ppf(0.975, dof) if math.isfinite(dof) else stats.norm.ppf(0.975)
            rej += int(abs(diff) > tc * se_difference(r_hat, d))
        out[q] = rej
    return out


# --------------------------------------------------------------------------- binary


def _prep_binary(chk: Check, rng: np.random.Generator) -> dict[str, Any]:
    d = chk.design
    mean = float(chk.params["mean"])
    # A large pilot (two identical arms) gives the probability-scale components.
    pilot = simulate(
        chk.comps, tasks=3000, repeats=max(d.repeats, 2), mean=mean, binary=True, seed=rng
    )
    est = estimate(pilot).components
    # Planned at the pilot's pass rate, with the variance at the shifted rate, for the
    # check's direction (+1: arm 1 passes more often, -1: less often).
    sign = int(chk.params.get("direction", 1))
    r = resolve(est, run=0.0, pass_rate=float(pilot["score"].mean()))
    target = mde(r, d, direction=sign)
    # Logit shift whose average effect on the pass probability equals the target.
    eta = mean + rng.normal(0, math.sqrt(chk.comps.item + chk.comps.item_arm), 200_000)
    base = float(np.mean(1 / (1 + np.exp(-eta))))

    def gap(s: float) -> float:
        return sign * (float(np.mean(1 / (1 + np.exp(-(eta + sign * s))))) - base) - target

    lo, hi = 0.0, 1.0
    while gap(hi) < 0:
        hi *= 2
        if hi > 64:
            raise ValueError(f"{chk.name}: no logit shift moves the pass rate by {target:.3g}")
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if gap(mid) < 0 else (lo, mid)
    return {
        "mde": target,
        "mde_base_rate": mde(resolve(est, run=0.0), d),
        "logit_shift": sign * (lo + hi) / 2,
        "base_pass": base,
        "pilot": est.to_dict(),
        "nominal": {"null": 0.05, "at_mde": 0.8},
    }


def _count_binary(chk, ctx, sims, rng, prof) -> dict[str, int]:  # type: ignore[no-untyped-def]
    d = chk.design
    out = {}
    for q, eff in (("null", 0.0), ("at_mde", ctx["logit_shift"])):
        rej = 0
        for _ in range(sims):
            df = simulate(
                chk.comps, tasks=d.tasks, repeats=d.repeats, mean=float(chk.params["mean"]),
                effect=eff, binary=True, seed=rng,
            )  # fmt: skip
            means = df.groupby(["arm", "item"])["score"].mean().unstack("item")
            diff = (means.loc["arm1"] - means.loc["arm0"]).to_numpy()[None, :]
            rej += int(_paired_t_reject(diff, 0.05)[0])
        out[q] = rej
    return out


# --------------------------------------------------------------------------- borrowed


def _pilot(chk: Check) -> tuple[int, int]:
    """Pilot (arms, runs per arm)."""
    return int(chk.params["pilot_arms"]), int(chk.params["pilot_runs"])


def _prep_borrowed(chk: Check, rng: np.random.Generator) -> dict[str, Any]:
    arms, runs = _pilot(chk)
    run_df = float(arms * (runs - 1))
    target = mde(resolve(chk.comps, run_df=run_df), chk.design)
    return {"mde": target, "run_df": run_df, "nominal": {"null": 0.05, "at_mde": 0.8}}


def _count_borrowed(chk, ctx, sims, rng, prof) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Pilot estimate of the run variance, then a test of a fresh one-run-per-arm experiment."""
    d = chk.design
    arms, runs = _pilot(chk)
    out = {}
    for q, eff in (("null", 0.0), ("at_mde", ctx["mde"])):
        diffs = _item_differences(chk.comps, d, eff, sims, rng)
        rej = 0
        for row in diffs:
            pilot = estimate(simulate(chk.comps, tasks=d.tasks, arms=arms, runs=runs, seed=rng))
            v_items = float(np.var(row, ddof=1)) / d.tasks
            v_run = 2.0 * max(pilot.components.run, 0.0) / d.runs
            terms = [(v_items, d.tasks - 1), (v_run, float(pilot.run_term.df))]
            denom = sum(v * v / k for v, k in terms if v > 0)
            dof = (v_items + v_run) ** 2 / denom
            rej += int(abs(row.mean()) > stats.t.ppf(0.975, dof) * math.sqrt(v_items + v_run))
        out[q] = rej
    return out


# --------------------------------------------------------------------------- coverage


def _coverage_names(chk: Check) -> list[str]:
    return [n for n in ("item", "item_arm", "item_run", "within") if getattr(chk.comps, n) > 0]


def _prep_coverage(chk: Check, rng: np.random.Generator) -> dict[str, Any]:
    nominal = {n: 0.95 for n in _coverage_names(chk)}
    if chk.design.runs > 1:
        nominal["run (MLS)"] = 0.95
    return {"nominal": nominal}


def _count_coverage(chk, ctx, sims, rng, prof) -> dict[str, int]:  # type: ignore[no-untyped-def]
    d = chk.design
    arms = int(chk.params.get("arms", 2))
    hits = {q: 0 for q in ctx["nominal"]}
    for _ in range(sims):
        df = simulate(chk.comps, tasks=d.tasks, arms=arms, runs=d.runs, repeats=d.repeats, seed=rng)
        b = bootstrap(df, draws=prof["boot"], seed=int(rng.integers(2**31)))
        for n in _coverage_names(chk):
            lo, hi = b.components[n]
            hits[n] += int(lo <= getattr(chk.comps, n) <= hi)
        if d.runs > 1:
            lo, hi = estimate(df).run_term.interval()
            hits["run (MLS)"] += int(lo <= chk.comps.run <= hi)
    return hits


# --------------------------------------------------------------------------- pairs


def _prep_pairs(chk: Check, rng: np.random.Generator) -> dict[str, Any]:
    return {"nominal": {"null (run-aware pair test)": 0.05, "run (MLS)": 0.95}}


def _count_pairs(chk, ctx, sims, rng, prof) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Simulate the layout, then the study's pair test of arm0 (partial run) vs arm3."""
    from evalnoise.study import _pairs_with_run_term

    hits = {q: 0 for q in ctx["nominal"]}
    pair = [("arm0", "arm3")]
    for _ in range(sims):
        parts = []
        for a, (runs, v) in enumerate(zip(chk.params["runs"], chk.params["item_run"], strict=True)):
            c = dataclasses.replace(chk.comps, item_run=v)
            parts.append(
                simulate(c, tasks=chk.design.tasks, arms=1, runs=runs, seed=rng).assign(
                    arm=f"arm{a}"
                )
            )
        df = pd.concat(parts, ignore_index=True)
        n_keep = int(chk.design.tasks * chk.params["partial"])
        partial = (df["arm"] == "arm0") & (df["run"] == "r1")
        df = df[~partial | (df["item"].str[1:].astype(int) < n_keep)]
        df = df.assign(cluster="g" + (df["item"].str[1:].astype(int) // 2).astype(str))
        est = estimate(df, pairs=pair)
        run_df = float(est.run_term.df)
        p = _pairs_with_run_term(est.pairs, pair, df, est.components, run_df)["arm0 - arm3"]
        hits["null (run-aware pair test)"] += int(p["p_with_run"] < 0.05)
        lo, hi = est.run_term.interval()
        hits["run (MLS)"] += int(lo <= chk.comps.run <= hi)
    return hits


RUNNERS: dict[str, tuple[Prepare, Count, str]] = {
    "power": (_prep_power, _count_power, "sims"),
    "naive": (_prep_naive, _count_naive, "sims"),
    "runs": (_prep_power, _count_runs, "run_sims"),
    "binary": (_prep_binary, _count_binary, "binary_sims"),
    "borrowed": (_prep_borrowed, _count_borrowed, "run_sims"),
    "coverage": (_prep_coverage, _count_coverage, "coverage_sims"),
    "pairs": (_prep_pairs, _count_pairs, "run_sims"),
}


def _log(out: Path, msg: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (out / "progress.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {msg}\n")


def validation_markdown(results: list[dict[str, Any]], profile: str) -> str:
    lines = [
        "# evalnoise validation results",
        "",
        f"Profile `{profile}`. Generated by `evalnoise validate`; do not edit by hand.",
        "Rates with exact 95% Monte Carlo intervals; `nominal` is what the planner predicts",
        "(or the interval's stated level, for coverage checks).",
        "",
        "| check | quantity | rate [MC 95%] | nominal | sims |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for r in results:
        for q, v in r["rates"].items():
            lo, hi = v["mc95"]
            lines.append(
                f"| `{r['name']}` | {q} | {v['rate']:.3f} [{lo:.3f}, {hi:.3f}] | "
                f"{v['nominal']:.3f} | {r['sims']} |"
            )
    lines.append("")
    return "\n".join(lines)
