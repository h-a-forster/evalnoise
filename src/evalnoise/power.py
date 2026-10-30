"""Minimum detectable effects and required tasks, repeats and runs for two-arm comparisons.

For two arms with ``T`` items each, ``R`` runs per arm and ``K`` repeats per item per run,
the variance of the difference in arm means under the model in
:mod:`evalnoise.components` is::

    paired   (same items in both arms):
        2 * (item_arm + item_run / R + within / (R K)) / T  +  2 * run / R
    unpaired (independent item samples per arm):
        2 * (item + item_arm + item_run / R + within / (R K)) / T  +  2 * run / R

The run term does not shrink with more items or repeats: only more runs per arm reduce it.
A component that the data could not separate is handled conservatively (see
:func:`resolve`), so the reported MDE is never smaller than the model implies.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from scipy import integrate, optimize, stats

from evalnoise.components import Components


@dataclass(frozen=True)
class Design:
    tasks: int
    runs: int = 1
    repeats: int = 1
    paired: bool = True

    def __post_init__(self) -> None:
        if self.tasks < 2:
            raise ValueError("tasks must be at least 2")
        if self.runs < 1 or self.repeats < 1:
            raise ValueError("runs and repeats must be at least 1")

    @property
    def trials_per_arm(self) -> int:
        return self.tasks * self.runs * self.repeats


@dataclass(frozen=True)
class Resolved:
    """Finite, non-negative components ready for planning, plus notes on assumptions."""

    item: float
    item_arm: float
    run: float
    item_run: float
    within: float
    notes: tuple[str, ...]
    # Degrees of freedom of the run-variance estimate available besides the experiment's
    # own replicate runs (e.g. from a pilot); inf = known exactly, 0 = none.
    run_df: float = math.inf


def resolve(
    c: Components,
    *,
    run: float | None = None,
    paired: bool = True,
    run_df: float = math.inf,
) -> Resolved:
    """Turn estimated components into planning inputs.

    ``run`` overrides the run variance (required when the data had one run per arm).
    ``run_df`` is the degrees of freedom of the run-variance estimate the analysis can
    borrow (a pilot's pooled runs minus one); the analysis pools it with the experiment's
    own ``2 (R - 1)``. The default treats the run variance as known exactly.
    Unidentified residual parts are set to zero only when they are already folded into a
    component that does not shrink with repeats or runs, which errs towards a larger MDE.
    """
    c = c.clipped()
    notes: list[str] = []
    if run is not None:
        if not math.isfinite(run) or run < 0:
            raise ValueError("run variance must be a non-negative number")
        run_v = float(run)
        if math.isfinite(c.run):
            notes.append(f"run variance set to {run_v:.4g} (estimated {c.run:.4g})")
        else:
            notes.append(f"run variance set to {run_v:.4g} (not identified by the data)")
    elif math.isfinite(c.run):
        run_v = c.run
    else:
        raise ValueError(
            "the run variance is not identified (one run per arm); supply it, or pass 0 "
            "to assume runs do not differ"
        )
    item_arm = c.item_arm
    if paired and not math.isfinite(item_arm):
        raise ValueError("paired planning needs the item x arm variance (data with two arms)")
    item_arm = item_arm if math.isfinite(item_arm) else 0.0
    if not paired and not math.isfinite(c.item):
        raise ValueError("unpaired planning needs the item variance")
    item = c.item if math.isfinite(c.item) else 0.0
    item_run = c.item_run if math.isfinite(c.item_run) else 0.0
    within = c.within if math.isfinite(c.within) else 0.0
    if c.absorbed.get("within") == "item_run":
        notes.append(
            "within-run noise is not separated from item x run noise: repeats inside a run "
            "are assumed not to help (conservative)"
        )
    if "item_run" in c.absorbed and c.absorbed["item_run"] != "item_run":
        notes.append(
            f"item x run noise is folded into {c.absorbed['item_run']}: extra runs are assumed "
            "not to reduce it (conservative)"
        )
    if c.absorbed.get("within") in ("item_arm", "item"):
        notes.append(
            "no repeats or replicate runs: trial noise is folded into the item terms, so "
            "repeats are assumed not to help (conservative)"
        )
    if not run_df >= 0:
        raise ValueError("run_df must be non-negative (inf = run variance known)")
    return Resolved(item, item_arm, run_v, item_run, within, tuple(notes), float(run_df))


def variance_terms(r: Resolved, d: Design) -> tuple[float, float]:
    """(item-level term, run term) of the variance of the estimated difference."""
    per_item = r.item_arm + r.item_run / d.runs + r.within / (d.runs * d.repeats)
    if not d.paired:
        per_item += r.item
    return 2.0 * per_item / d.tasks, 2.0 * r.run / d.runs


def se_difference(r: Resolved, d: Design) -> float:
    v_items, v_run = variance_terms(r, d)
    return math.sqrt(v_items + v_run)


def _df(r: Resolved, d: Design) -> float:
    """Satterthwaite degrees of freedom of the variance estimate the analysis would use."""
    v_items, v_run = variance_terms(r, d)
    df_items = (d.tasks - 1) if d.paired else 2 * (d.tasks - 1)
    terms = [(v_items, df_items)]
    if v_run > 0:
        df_run = 2 * (d.runs - 1) + r.run_df
        if df_run == 0:
            raise ValueError(
                "one run per arm and no other estimate of the run variance: a test cannot "
                "estimate the run term; add runs or supply run_df from a pilot"
            )
        terms.append((v_run, df_run))
    denom = sum(v * v / df for v, df in terms)
    total = v_items + v_run
    return math.inf if denom == 0 else total * total / denom


def power_at(
    r: Resolved, d: Design, effect: float, *, alpha: float = 0.05, method: str = "t"
) -> float:
    """Two-sided power to detect ``effect`` (score units) at level ``alpha``."""
    _check_level(alpha, "alpha")
    if method not in ("t", "z"):
        raise ValueError("method must be 't' or 'z'")
    se = se_difference(r, d)
    if se == 0:
        return 1.0 if effect != 0 else alpha
    ncp = abs(effect) / se
    df = _df(r, d) if method == "t" else math.inf
    if math.isinf(df):
        zc = stats.norm.ppf(1 - alpha / 2)
        return float(stats.norm.sf(zc - ncp) + stats.norm.cdf(-zc - ncp))
    tc = stats.t.ppf(1 - alpha / 2, df)
    return _t_power(float(tc), df, ncp)


def _t_power(tc: float, df: float, ncp: float) -> float:
    """P(|T| > tc) for noncentral t; scipy's nct returns nan in parts of the parameter space."""
    p = float(stats.nct.sf(tc, df, ncp) + stats.nct.cdf(-tc, df, ncp))
    if math.isfinite(p):
        return min(max(p, 0.0), 1.0)
    if df > 1e4:
        return float(stats.norm.sf(tc - ncp) + stats.norm.cdf(-tc - ncp))
    return _t_power_quad(tc, df, ncp)


def _t_power_quad(tc: float, df: float, ncp: float) -> float:
    """T = (Z + ncp) / sqrt(X / df), X ~ chi2(df): integrate the normal tails over X."""

    def f(x: float) -> float:
        s = tc * math.sqrt(x / df)
        return float(stats.chi2.pdf(x, df) * (stats.norm.sf(s - ncp) + stats.norm.cdf(-s - ncp)))

    val, _ = integrate.quad(f, 0.0, math.inf, limit=200)
    return min(max(float(val), 0.0), 1.0)


def mde(
    r: Resolved, d: Design, *, alpha: float = 0.05, power: float = 0.8, method: str = "t"
) -> float:
    """Smallest absolute effect detected with probability ``power`` at level ``alpha``."""
    _check_level(alpha, "alpha")
    _check_level(power, "power")
    se = se_difference(r, d)
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    if se == 0:
        return 0.0
    if method == "z":
        return float(z * se)
    if method != "t":
        raise ValueError("method must be 't' or 'z'")
    hi = z * se
    while power_at(r, d, hi, alpha=alpha) < power:
        hi *= 2.0
    return float(
        optimize.brentq(lambda e: power_at(r, d, e, alpha=alpha) - power, 0.0, hi, xtol=1e-12)
    )


def tasks_needed(
    r: Resolved,
    target: float,
    *,
    runs: int = 1,
    repeats: int = 1,
    paired: bool = True,
    alpha: float = 0.05,
    power: float = 0.8,
    method: str = "t",
    max_tasks: int = 1_000_000,
) -> int | None:
    """Fewest tasks per arm whose MDE is at most ``target``; ``None`` if unreachable.

    Unreachable means the run term alone exceeds the budget: add runs, not tasks.
    """
    if target <= 0:
        raise ValueError("target effect must be positive")

    def ok(t: int) -> bool:
        return (
            mde(r, Design(t, runs, repeats, paired), alpha=alpha, power=power, method=method)
            <= target
        )

    if not ok(max_tasks):
        return None
    lo, hi = 2, 2
    while not ok(hi):
        lo, hi = hi, min(hi * 2, max_tasks)
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid + 1
    return hi


def naive_false_positive_rate(r: Resolved, d: Design, *, alpha: float = 0.05) -> float:
    """False-positive rate of a test that ignores run effects (e.g. paired over items).

    Such a test estimates only the item-level term of the variance, so a run-to-run shift
    reads as an arm difference. Equals ``alpha`` when the run variance is zero.
    """
    v_items, v_run = variance_terms(r, d)
    if v_items + v_run == 0:
        return alpha
    zc = stats.norm.ppf(1 - alpha / 2)
    return float(2 * stats.norm.sf(zc * math.sqrt(v_items / (v_items + v_run))))


def optimal_repeats(r: Resolved, *, runs: int = 1, task_cost: float = 0.0) -> float:
    """Repeats per item per run that minimise variance for a fixed budget.

    ``task_cost`` is the extra cost of adding a task, in units of one trial (0 when tasks
    already exist and only trials cost money). With ``task_cost = 0`` the answer is 1: a
    new task always buys more precision than another repeat of an old one.
    """
    if task_cost < 0:
        raise ValueError("task_cost must be non-negative")
    a = r.item_arm + r.item_run / runs
    b = r.within / runs
    if task_cost == 0 or b == 0:
        return 1.0
    if a == 0:
        return math.inf
    return max(1.0, math.sqrt(b * task_cost / (a * runs)))


def plan(
    r: Resolved,
    tasks: Iterable[int],
    runs: Iterable[int] = (1,),
    repeats: Iterable[int] = (1,),
    *,
    paired: bool = True,
    alpha: float = 0.05,
    power: float = 0.8,
    method: str = "t",
) -> list[dict[str, float | int]]:
    """MDE, standard error and naive false-positive rate over a grid of designs."""
    rows: list[dict[str, float | int]] = []
    for nr in runs:
        for k in repeats:
            for t in tasks:
                d = Design(t, nr, k, paired)
                rows.append(
                    {
                        "tasks": t,
                        "runs": nr,
                        "repeats": k,
                        "trials_per_arm": d.trials_per_arm,
                        "se": se_difference(r, d),
                        "mde": mde(r, d, alpha=alpha, power=power, method=method),
                        "naive_fpr": naive_false_positive_rate(r, d, alpha=alpha),
                    }
                )
    return rows


def _check_level(x: float, name: str) -> None:
    if not 0 < x < 1:
        raise ValueError(f"{name} must be between 0 and 1")
