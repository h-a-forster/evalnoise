"""Numbers REPORT.md marks as derived: run-blind false-positive rates for literally
identical setups (item x arm = 0) and the mm-arena reference design refitted without the
haiku setup. Run from the repository root: uv run python scripts/derived_numbers.py"""

import dataclasses
import math

from evalnoise.components import estimate
from evalnoise.data import load_trials
from evalnoise.power import Design, naive_false_positive_rate, resolve, se_difference

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
