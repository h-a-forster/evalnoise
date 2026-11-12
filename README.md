# evalnoise

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

How noisy is an agent eval, and how many tasks, repeats and runs does a comparison need?

evalnoise splits the variance of per-trial eval scores into five parts: item (task
difficulty), item x arm (tasks that favour one configuration), run (a shift shared by a
whole run: a CLI or API version, a bad hour, a harness fix), item x run, and trial noise
within a run. It gives each part an interval, says which parts your data cannot separate,
and turns them into a plan: the minimum detectable effect (MDE) of a design, the number of
tasks needed for a target MDE, and how often a test that ignores run effects will report
a difference between two configurations with equal mean scores.

Item-level confidence intervals, paired or clustered, cannot see the run term. How large it
is depends on what changes between runs: see [Findings](#findings).

Python 3.11+, depends on numpy, scipy and pandas. No model calls, no network.

## Findings

From [REPORT.md](REPORT.md), a quick-profile study of per-trial data published by four
small agent-eval projects, all on Claude models. These are a handful of datasets, not a
survey; treat the numbers as examples of what the tool shows.

- **In mm-arena, run-to-run shifts came mostly from one setup across Claude Code
  versions.** mm-arena has 120 market-making episodes and four Claude setups run two to
  four times each. The run SD pooled over the setups was 2.9 pp of edge captured (95% CI
  1.6 to 6.4) on 7 df, and 81% of its sum of squares is the Haiku setup (fitted alone:
  4.0 pp, against 1.3, 1.7 and 1.5 for the others), whose runs span Claude Code versions.
  Its one pair of runs on the same recorded version (runs 3 and 4) agreed within episode
  noise (1.4 pp apart); the model has no harness factor, so it cannot separate version
  changes from drift. With the pooled variances, a pair of setups compared from one run
  each has an estimated SE of 4.7 pp, not the 2.3 pp an item-level interval reports, and
  a run-blind paired test calls two setups with equal mean scores different 33% of the
  time (CI 17% to 62%). Without Haiku the run SD is 1.6 pp (0.5 to 5.2) and that rate
  19%. Both rates treat episodes as independent; with the episodes' clustering the
  item-level SE is larger, so they are upper-end figures.
- **Reruns of a fixed setup barely shift scores.** [trialnoise](https://github.com/h-a-forster/trialnoise),
  which reuses these estimators on 46,830 public Terminal-Bench 2 trials, found that
  replicate jobs of 20 multi-vendor submissions (72 df) give a run variance that
  estimates below zero, with an upper limit of 0.9 points of run SD. The two results
  measure different things: trialnoise's replicate jobs rerun one fixed submission a
  median of two days apart (and submitters chose which to publish), while mm-arena's
  runs changed the Claude Code version and date, on a different score. Use trialnoise's
  run term for reruns of an unchanged setup, and mm-arena's as an example of what a
  harness or version change can add.
- **Where runs do shift, more episodes cannot fix it; more runs can,** as far as run
  shifts are shared by every episode. With mm-arena's pooled estimates, and allowing for
  the seeds that pair up within games (design effect 1.24), a 10 pp difference needs 3
  runs per setup with 70 episodes, or 4 with 51; 5 pp needs 20 runs with 133 episodes (10
  runs need 234), beyond the 120 episodes available. Run shifts also differed by task
  family (one setup: +1.7 to +22.8 pp), so part of the run term may shrink with more task
  families.
- **Pass/fail evals with one run per arm cannot identify the run term at all.** For
  agent-ab and overclaim (18 to 50 coding tasks) the MDEs of the published designs are
  8.3 to 14.7 pp before any run effect, which understates them if runs vary. Near a 94%
  pass rate a loss is harder to detect than a gain (the variance grows towards 50%), and
  the planner takes the larger. Trial noise within a run was large (SD 18 to 22 pp of
  pass rate), so repeats helped there: 5 pp on agent-ab needs 326 tasks with one repeat
  or 116 with three.
- **The planner is calibrated where its assumptions hold.** In simulation, power at the
  planned MDE was 0.79 to 0.81 and size 0.04 to 0.06 for paired item-level tests; the
  false-positive formula for run-blind tests matched simulation (0.615 vs 0.621, 0.370
  vs 0.356). Planning for pass/fail data from a pilot was conservative at 60 to 70% pass
  rates (power 0.85 to 0.87), and near a 90% pass rate a planned drop was detected with
  power 0.79 once the variance was taken at the shifted rate. In an mm-arena-like layout
  (2 to 4 runs per setup, a partial run, unequal residuals) the run-aware pair test had
  size 0.062 and the run-variance interval covered 0.95. Weak spots: with only three runs
  the run-aware test was somewhat liberal (size 0.077), and with the run variance
  borrowed on 7 df (as for mm-arena) slightly so (size 0.068, power 0.80 at the planned
  MDE); and the bootstrap interval for item x arm undercovered with 40 items (0.85).

## Install

Not on PyPI. From a clone:

```sh
uv sync
uv run evalnoise --version
```

or `pip install git+https://github.com/h-a-forster/evalnoise`.

## Quick start

Estimate the components. This uses a table shipped in `results/trials/` (agent-ab:
Claude Code on Haiku 5.5, 50 tasks, 3 repeats, with and without an instruction to skip
tests; pass/fail scaled to percentage points):

```sh
uv run evalnoise components results/trials/agent-ab-no-tests.csv \
    --score-col passed --scale 100 --pair no-tests,control
```

```text
300 trials, 50 items (50 clusters), 2 arm(s), runs per arm [1], up to 3 repeats per run
| component | variance | SD [95%] | interval |
| --- | ---: | ---: | --- |
| item | 191.8 | 13.851 [0.000, 23.503] | bootstrap, 1000 draws |
| item x arm | 10.2 | 3.194 [0.000, 9.053] | bootstrap, 1000 draws |
| run | - | - | not identified |
| item x run | - | - | folded into item x arm |
| within run | 366.7 | 19.149 [12.910, 23.805] | bootstrap, 1000 draws |
no-tests - control: difference -2.667, item-level SE 2.302, item x arm SD 3.194 over 50 items
```

Plan a comparison from those estimates:

```sh
uv run evalnoise power results/trials/agent-ab-no-tests.csv --score-col passed --scale 100 \
    --run-var 0 --tasks 20,50,100 --repeats 1,3 --mde 5,10
```

```text
paired comparison of two arms, alpha 0.05, power 0.8, estimated from 300 trials; SD item 13.9, item x arm 3.19, run 0, item x run 0, within 19.1
note: run variance set to 0 (not identified by the data)
note: item x run noise is folded into item_arm: extra runs are assumed not to reduce it (conservative)
| tasks | runs | repeats | trials/arm | SE | MDE | naive FPR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20 | 1 | 1 | 20 | 6.14 | 18.1 | 5% |
| 50 | 1 | 1 | 50 | 3.88 | 11.1 | 5% |
| 100 | 1 | 1 | 100 | 2.75 | 7.77 | 5% |
| 20 | 1 | 3 | 60 | 3.64 | 10.7 | 5% |
| 50 | 1 | 3 | 150 | 2.3 | 6.58 | 5% |
| 100 | 1 | 3 | 300 | 1.63 | 4.6 | 5% |
naive FPR: false-positive rate of a test that ignores run effects (nominal alpha).
MDE 5 with 1 run(s) x 1 repeat(s): 239 tasks per arm
MDE 5 with 1 run(s) x 3 repeat(s): 86 tasks per arm
MDE 10 with 1 run(s) x 1 repeat(s): 62 tasks per arm
MDE 10 with 1 run(s) x 3 repeat(s): 23 tasks per arm
```

These are pass/fail scores at a 94% pass rate, where a drop is harder to detect than a
gain: add `--pass-rate 0.94 --pass-score 100` to take the variance at the shifted rate
(MDE 5 with one repeat then needs 326 tasks per arm). `--design-effect` multiplies the
item-level variance when items come in correlated clusters.

This table has one run per arm, so the run variance is unknown: `power` refuses to guess
until you pass `--run-var` (0 assumes no run effects, which understates every MDE if runs
do vary).
You can also plan from components measured elsewhere:

```sh
uv run evalnoise power --components item=400,item_arm=60,run=20,item_run=100,within=300 \
    --tasks 20,50,100 --runs 1,2,5 --mde 10
```

which reports, among others, `MDE 10 with 1 run(s) x 1 repeat(s): unreachable (add runs,
not tasks)` and `MDE 10 with 5 run(s) x 1 repeat(s): 60 tasks per arm`.

From Python:

```python
from evalnoise import Design, estimate, load_trials, mde, resolve, tasks_needed

df = load_trials("results/trials/agent-ab-no-tests.csv", {"score": "passed"})
df["score"] *= 100
est = estimate(df, pairs=[("no-tests", "control")])
plan = resolve(est.components, run=0.0)  # run variance not identified: assume 0
print(mde(plan, Design(tasks=50, repeats=3)))  # 6.58
print(tasks_needed(plan, 5.0, repeats=3))  # 86
```

Your own results: one row per trial with columns `item`, `arm`, `score` and optionally
`run`, `repeat` and `cluster` (items nested in larger units that should be resampled
together). Map other names with `--item-col`, `--arm-col`, `--run-col`, `--cluster-col`,
`--score-col`. Inspect JSON logs and lm-eval `samples_*.jsonl` files are read directly.

## Commands

| Command | What it does |
|---|---|
| `evalnoise components FILE...` | variance components with intervals, optional `--reml` cross-check and `--pair` differences |
| `evalnoise power [FILE... \| --components ...]` | MDE grid, tasks needed (`--mde`), cost-optimal repeats (`--task-cost`) |
| `evalnoise extract` | rebuild `results/trials/` from source checkouts (`configs/sources.toml`) |
| `evalnoise study` | the study over `results/trials/` (`configs/study.toml`), resumable |
| `evalnoise validate` | Monte Carlo checks of the planner and intervals, resumable |

## How it works

The model, estimands, what each data layout can identify, the estimators (Henderson
method III for runs, ANOVA for items, a REML cross-check), the intervals and the
validation plan are in [docs/DESIGN.md](docs/DESIGN.md), with prior work. In short:

- paired difference variance: `2 (item_arm + item_run / R + within / (R K)) / T + 2 run / R`
  for `T` tasks, `R` runs per arm and `K` repeats per task per run;
- the run term ignores `T` and `K`: only runs reduce it;
- components the data cannot separate are folded where they do not shrink, so folding
  never lowers the MDE; a component that is neither given nor folded is an error.

## Limitations

- The study covers four small projects, all on Claude models through Claude Code or the
  Claude CLI; only mm-arena has replicate runs of unchanged setups (ruleproof's replicate
  runs changed the hook build), and its run variance rests on 7 degrees of freedom.
- The pass/fail tables keep tasks no trial passed (overclaim's impossible tasks and a
  check that probably conflicted with its prompt). These make up most of the item SDs
  there and lower the pooled pass rates; on overclaim's 18 solvable tasks the MDE is
  18.4 pp, not 11.5. The source setups also differ: overclaim's agents saw the host's
  user-level instructions. See [REPORT.md](REPORT.md#data).
- Variances are assumed common to all arms; the study reports per-arm run terms and tests
  the item x run variance for equality (Brown-Forsythe; the mm-arena setups fail it).
- Pass/fail outcomes are analysed on the 0/1 scale. The planner takes the shifted arm's
  variance at its own pass rate where larger, which held power for drops near a 90% pass
  rate in simulation; elsewhere it keeps the base-rate variance (conservative there).
- The planner treats items as independent unless given a design effect; the study applies
  the game design effect (mm-arena: two seeds per game) to its tasks-needed tables only,
  reports the family one (five task families, too few to apply) and clustered pair SEs,
  and breaks run shifts down by family.
- Runs are treated as exchangeable draws and there is no harness-version factor; a
  harness update between runs is really a fixed shift. Trial tables keep the harness
  version per run where the source records it, but only one mm-arena setup has two runs
  on one recorded version, too few to estimate the split.
- More in [REPORT.md](REPORT.md#limitations).

## Related work

Miller (2024), [arXiv:2411.00640](https://arxiv.org/abs/2411.00640); Bjarnason, Silva and
Monperrus (2026), [arXiv:2602.07150](https://arxiv.org/abs/2602.07150); Chandrahas (2026),
evalci, [arXiv:2607.04429](https://arxiv.org/abs/2607.04429); Messing (2026),
[arXiv:2604.11581](https://arxiv.org/abs/2604.11581); Zhang et al. (2026),
[arXiv:2605.23950](https://arxiv.org/abs/2605.23950); Mustahsan et al. (2025),
[arXiv:2512.06710](https://arxiv.org/abs/2512.06710). How evalnoise relates to each:
[docs/DESIGN.md](docs/DESIGN.md#9-prior-art).

## Licence

MIT. See [LICENSE](LICENSE). Citation metadata: [CITATION.cff](CITATION.cff).
