"""Numbers REPORT.md marks as derived: run-blind false-positive rates for literally
identical setups (item x arm = 0), the mm-arena reference design refitted without the
haiku setup, its episode-only SE scaled by the game design effect, and haiku's share of the
run sum of squares, the run term of each setup refitted on its runs from one recorded
harness version, agent-ab's one-run MDE from the base-rate variance, and the pass/fail
tables without the tasks no trial passes. Run from the repository root:
uv run python scripts/derived_numbers.py"""

import dataclasses
import itertools
import math

import numpy as np
import pandas as pd

from evalnoise.components import estimate
from evalnoise.data import load_trials
from evalnoise.power import Design, mde, naive_false_positive_rate, resolve, se_difference

df = load_trials("results/trials/mm-arena.csv", {"score": "edge_pp"})
runs = df.groupby("arm")["run"].nunique()
replicated = sorted(runs[runs >= 2].index)
ref = Design(120, 1, 1)  # the study's reference design for mm-arena
fits = {
    "mm-arena-replicated": replicated,
    "replicated without haiku": [a for a in replicated if "haiku" not in a],
    "mm-arena-all": sorted(df["arm"].unique()),
}
for name, arms in fits.items():
    est = estimate(df, arms=arms)
    c = est.components
    r = resolve(c, run_df=est.run_term.df)
    same = resolve(dataclasses.replace(c, item_arm=0.0), run_df=est.run_term.df)
    print(
        f"{name}: run SD {math.sqrt(c.run):.2f}, SE {se_difference(r, ref):.2f}, "
        f"naive rate {naive_false_positive_rate(r, ref):.3f}, "
        f"identical setups {naive_false_positive_rate(same, ref):.3f}"
    )

# Episode-only SE of the reference design, and with the two seeds of a game correlated:
# scaled by the median game design effect over the replicated pairs (as in the study).
est = estimate(df, arms=replicated, pairs=list(itertools.combinations(replicated, 2)))
c = est.components
se_items = se_difference(resolve(dataclasses.replace(c, run=0.0)), ref)
deff = float(np.median([(p["se_clusters"] / p["se_items"]) ** 2 for p in est.pairs.values()]))
haiku = [a for a in replicated if "haiku" in a]
share = sum(est.run_terms[a].ss for a in haiku) / est.run_term.ss
print(
    f"mm-arena-replicated: SE episodes only {se_items:.3f}, game design effect {deff:.3f}, "
    f"SE games {se_items * math.sqrt(deff):.3f}; haiku share of run sum of squares {share:.3f}"
)

# Within one harness version: the run term of a setup fitted on only its runs that share a
# recorded harness version (the model has no harness factor; this is a subset refit).
raw = pd.read_csv("results/trials/mm-arena.csv", usecols=["arm", "run", "harness"])
versions = raw[raw["harness"] != "unrecorded"].drop_duplicates()
for (arm, harness), v in versions.groupby(["arm", "harness"]):
    if len(v) < 2:
        continue
    g = df[(df["arm"] == arm) & df["run"].isin(v["run"])]
    rt = estimate(g, arms=[arm]).run_terms[arm]
    v, (lo, hi) = rt.variance(), rt.interval()
    sd = f"{math.sqrt(v):.2f}" if v > 0 else "<0"
    print(
        f"{arm} on {harness}, runs {'/'.join(sorted(g['run'].unique()))}: run SD {sd} "
        f"[{math.sqrt(max(lo, 0)):.2f}, {math.sqrt(max(hi, 0)):.2f}] on {rt.df} df, "
        f"item x run SD {math.sqrt(rt.rss / rt.df_res):.2f}"
    )

# agent-ab-no-tests (94% pass, 50 tasks x 3): the one-run MDE from the base-rate variance,
# against the study's, which takes the shifted arm's variance at its own rate where larger.
ab = load_trials("results/trials/agent-ab-no-tests.csv", {"score": "passed"})
ab = ab.assign(score=ab["score"] * 100)
c = estimate(ab).components
rate = float(ab["score"].mean()) / 100
d = Design(50, 1, 3)
print(
    f"agent-ab-no-tests: MDE {mde(resolve(c, run=0.0), d):.2f} from the base-rate variance, "
    f"{mde(resolve(c, run=0.0, pass_rate=rate, pass_score=100.0), d):.2f} at the shifted rate"
)

# Pass/fail tables without the tasks no trial passes: overclaim's impossible tasks, built to
# fail, and feature-uri-resolve, whose hidden check probably conflicted with its prompt.
IMPOSSIBLE = [
    "billing-month-end",
    "blobcache-codec-size",
    "oncall-rota",
    "procure-2019-prices",
    "triage-sort-comparisons",
]
BROKEN = ["feature-uri-resolve"]
for table, repeats, drop in (
    ("agent-ab-no-tests", 3, BROKEN),
    ("overclaim-setups", 2, IMPOSSIBLE),
    ("overclaim-setups", 2, IMPOSSIBLE + BROKEN),
    ("overclaim-interventions", 4, BROKEN),
):
    t = load_trials(f"results/trials/{table}.csv", {"score": "passed"})
    t = t[~t["item"].isin(drop)].assign(score=lambda x: x["score"] * 100)
    c = estimate(t).components
    rate = float(t["score"].mean()) / 100
    d = Design(t["item"].nunique(), 1, repeats)
    plan_r = resolve(c, run=0.0, pass_rate=rate, pass_score=100.0)
    print(
        f"{table} without {len(drop)} task(s): {d.tasks} tasks, pass rate {rate:.3f}, "
        f"item SD {math.sqrt(max(c.item, 0)):.1f}, within SD {math.sqrt(c.within):.1f}, "
        f"MDE {mde(plan_r, d):.1f}"
    )
