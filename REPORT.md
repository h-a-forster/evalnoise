# evalnoise report: variance components of four Claude agent evals

Quick profile, 2026-10-30. All numbers come from `results/study/summary.md` and
`results/validation/summary.md`, which `uv run evalnoise study` and
`uv run evalnoise validate` regenerate (about 4 minutes each on a laptop CPU). Intervals
are 95%. Model, estimators and interval methods: [docs/DESIGN.md](docs/DESIGN.md).

## Summary

- In the only dataset with replicate runs (mm-arena, three Claude setups run two or three
  times on 120 episodes), the run SD was **4.2 pp** of edge captured (**2.2 to 12.6**,
  chi-square, 4 df). For a paired comparison of two setups from one run each, that makes
  the SE of the difference **6.3 pp** instead of the **2.1 pp** the episodes alone give;
  the run term is 89% of the variance. A paired test over episodes, which ignores runs,
  would call two identical setups different **51%** of the time (**27% to 82%** across the
  run-variance interval) at a nominal 5%.
- With those estimates no number of episodes brings the MDE of a one-run-per-setup
  comparison below 10 pp. Five runs per setup with 45 episodes reach 10 pp; 5 pp needs
  about 20 runs. The run-variance interval is wide, so these counts are uncertain by a
  factor of several.
- In the pass/fail datasets with one run per arm (agent-ab, overclaim, ruleproof
  pressure), the run variance is not identified. Their MDEs at the published designs,
  6.6 pp (agent-ab, 50 tasks x 3), 11 pp (overclaim, 23 x 2 and 18 x 4) and 53 pp
  (ruleproof pressure, 5 tasks x 3), assume no run effect and are lower bounds. Trial
  noise within a run was SD 18 to 22 pp of pass rate (36 pp on ruleproof's pressure
  tasks), comparable to or larger than the task SD, so repeats there buy real precision.
- The planner reproduces its nominal power and size in simulation when its assumptions
  hold. Known gaps: the run-aware t-test is somewhat liberal with three runs per arm, and
  the percentile bootstrap undercovers the item x arm SD with 40 items.

These are nine analyses of seven tables from four small projects, all using Claude models
through Claude Code or the Claude CLI. They show what the method finds; they do not
establish how large run effects are for agent evals in general.

## Data

| Dataset | Source | Arms | Items | Runs per arm | Repeats | Trials | Score |
|---|---|---:|---:|---|---:|---:|---|
| `mm-arena-replicated` | [mm-arena](https://github.com/h-a-forster/mm-arena) core-v1 | 3 | 120 | 2-3 | 1 | 755 | edge captured, pp |
| `mm-arena-all` | same, all 9 LLM setups | 9 | 120 | 1-3 | 1 | 1475 | edge captured, pp |
| `agent-ab-no-tests` | [agent-ab](https://github.com/h-a-forster/agent-ab) | 2 | 50 | 1 | 3 | 300 | passed, pp |
| `agent-ab-no-tests-cost` | same | 2 | 50 | 1 | 3 | 300 | log cost (log USD) |
| `agent-ab-haiku-vs-sonnet` | same | 2 | 50 | 1 | 1 | 100 | passed, pp |
| `overclaim-setups` | [overclaim](https://github.com/h-a-forster/overclaim) study 1 | 4 | 23 | 1 | 2 | 184 | passed, pp |
| `overclaim-interventions` | overclaim study 2 | 4 | 18 | 1 | 4 | 288 | passed, pp |
| `ruleproof-main` | [ruleproof](https://github.com/h-a-forster/ruleproof) bench | 9 | 5 | 1-2 | 3 | 180 | all rules followed, pp |
| `ruleproof-pressure` | ruleproof pressure tasks | 6 | 5 | 1 | 3 | 80 | all rules followed, pp |

mm-arena episodes are items and games are bootstrap clusters (each game has two seeds that
share a hidden structure). The mm-arena replicate runs were still being generated when the
tables were extracted: `fable-5-1@high` r2 covered 84 of 120 episodes and `haiku-5-5@high`
r3 covered 71. The run fit adjusts for which episodes a partial run covers. Those files
are not yet committed upstream; `results/trials/MANIFEST.json` lists them with their
sha256. In ruleproof, the replicate runs of the three hook arms used different hook builds,
so their run term includes a code change.

## Variance components

SD in the dataset's unit; 95% cluster-bootstrap intervals, chi-square for run.
`n/i`: not identified; `(in X)`: folded into X.

| Dataset | item | item x arm | run | item x run | within run | ICC item |
|---|---:|---:|---:|---:|---:|---:|
| `mm-arena-replicated` | 54.8 [39.6, 67.8] | 8.4 [0.0, 14.0] | 4.2 [2.2, 12.6] | 14.2 [10.9, 17.1] | (in item x run) | 0.91 |
| `mm-arena-all` | 43.6 [33.0, 53.0] | 19.7 [15.9, 23.3] | 4.2 [2.2, 12.6] | 14.2 [10.8, 17.1] | (in item x run) | 0.76 |
| `agent-ab-no-tests` | 13.9 [0.0, 24.3] | 3.2 [0.0, 8.7] | n/i | (in item x arm) | 19.1 [12.9, 23.8] | 0.34 |
| `agent-ab-no-tests-cost` | 0.753 [0.489, 0.993] | 0.166 [0.027, 0.258] | n/i | (in item x arm) | 0.191 [0.140, 0.245] | 0.90 |
| `agent-ab-haiku-vs-sonnet` | 13.4 [0.0, 23.7] | 17.4 [0.0, 26.4] | n/i | (in item x arm) | (in item x arm) | 0.37 |
| `overclaim-setups` | 43.0 [27.8, 49.1] | 0.0 [0.0, 1.3] | n/i | (in item x arm) | 18.1 [10.4, 25.5] | 0.85 |
| `overclaim-interventions` | 22.8 [0.6, 37.1] | 0.0 [0.0, 0.0] | n/i | (in item x arm) | 22.3 [14.8, 28.7] | 0.51 |
| `ruleproof-main` | 9.5 [0.0, 12.0] | 19.6 [10.6, 21.3] | 0.0 [0.0, 8.8] | 0.0 [0.0, 7.5] | 22.4 [18.3, 25.8] | 0.09 |
| `ruleproof-pressure` | 26.2 [0.0, 35.9] | 7.5 [0.0, 14.8] | n/i | (in item x arm) | 36.5 [20.0, 47.6] | 0.33 |

Observations:

- **mm-arena: per-episode scores vary hugely between episodes** (item SD 55 pp: an
  episode's edge relative to the suite-average Bayes edge), which is why the leaderboard
  number needs many episodes. This cancels in paired comparisons (ICC 0.91). What does not
  cancel is the run term and the item x run term (SD 14 pp per episode: the agent's own
  randomness plus item-specific changes between runs).
- **The run means move visibly.** Over all 120 episodes, `opus-5-5@high` scored 87.7 and
  83.8 in its two runs and `haiku-5-5@high` 79.9 and 90.4; on the 71 episodes its partial
  third run covers, `haiku-5-5@high` scored 61.8, 74.8 and 67.2 in runs 1 to 3. The
  harness version was not recorded for runs 1 and 2, so a version change cannot be ruled
  out as the cause.
- **`mm-arena-all` pools single-run setups** under the assumption that all setups share
  the replicated setups' residual; its larger item x arm SD (19.7 vs 8.4) reflects that
  low-effort setups disagree with high-effort ones on which episodes are hard.
- **Pass/fail data near ceiling** (agent-ab 93 to 95% pass, overclaim interventions 88
  to 92%) give wide item intervals that reach 0, and item x arm estimates at the boundary.
  overclaim study 1 (pass rates 67 to 72%) has a much larger task SD (43 pp).
- **ruleproof has only 5 tasks**, so its item components are barely informative; its run
  estimate (hook arms, two builds) is 0 with an upper bound of 8.8 pp.
- **Cost** (agent-ab, log USD): tasks explain most of the variance (ICC 0.90); trial noise
  is SD 0.19 in log cost, about a 21% multiplicative spread.

### REML cross-check

The moment estimates agree with REML within their intervals. The largest difference is
`ruleproof-pressure` item x arm (7.5 vs 2.7 pp, interval 0 to 14.8; one arm has a single
repeat, so the layout is unbalanced); every other component differs by less than 2 pp
(`mm-arena-replicated` item x arm: 8.4 vs 8.8). All pairs are in
`results/study/summary.md`.

## Planning

Paired comparison of two arms, one run per arm, at each dataset's observed number of tasks
and repeats. Where identified, the run variance is borrowed with its degrees of freedom
(4 for mm-arena), which widens the t quantiles.

| Dataset | Tasks x repeats | SE, items only | SE with run term | MDE | MDE at run CI ends | Naive false-positive rate |
|---|---|---:|---:|---:|---:|---:|
| `mm-arena-replicated` | 120 x 1 | 2.1 | 6.3 | 21.9 | 12.1 to 66.8 | 51% [27%, 82%] |
| `mm-arena-all` | 120 x 1 | 3.1 | 6.7 | 22.1 | 13.3 to 66.7 | 36% [17%, 73%] |
| `agent-ab-no-tests` | 50 x 3 | 2.3 | n/i | 6.6 [4.7, 8.7] | - | n/i |
| `agent-ab-haiku-vs-sonnet` | 50 x 1 | 3.5 | n/i | 10.0 [0.0, 15.1] | - | n/i |
| `overclaim-setups` | 23 x 2 | 3.8 | n/i | 11.0 [6.4, 15.6] | - | n/i |
| `overclaim-interventions` | 18 x 4 | 3.7 | n/i | 11.1 [7.3, 14.2] | - | n/i |
| `ruleproof-main` | 5 x 3 | 14.9 | 14.9 | 55.9 [37.0, 59.8] | 55.9 to 63.3 | 5% [5%, 13%] |
| `ruleproof-pressure` | 5 x 3 | 14.1 | n/i | 53.2 [31.0, 65.7] | - | n/i |

MDE in pp, 80% power, alpha 0.05; brackets are item-bootstrap intervals (run variance held
at its estimate). For mm-arena the item-bootstrap interval is negligible next to the
run-variance interval, shown separately.

Tasks per arm for a target MDE (selected rows; R runs per arm, K repeats per task per run;
"never": the run term alone exceeds the target):

| Dataset | Target | R1 K1 | R1 K3 | R3 K1 | R5 K1 | R10 K1 | R20 K1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `mm-arena-replicated` | 10 pp | never | never | never | 45 | 22 | 17 |
| `mm-arena-replicated` | 5 pp | never | never | never | never | never | 118 |
| `agent-ab-no-tests` (lower bound) | 5 pp | 239 | 86 | 86 | 55 | - | - |
| `agent-ab-no-tests` (lower bound) | 10 pp | 62 | 23 | 23 | 16 | - | - |
| `overclaim-interventions` (lower bound) | 10 pp | 81 | 29 | 29 | 18 | - | - |

For mm-arena, repeats within a run do not help in this table because within-run noise is
not separated from item x run noise there (no repeats inside a run); the planner then
assumes, conservatively, that only new runs average it out.

## Pairwise differences, with and without the run term

For mm-arena, the items-only SE understates the uncertainty of every pair:

| Pair (mm-arena) | Difference, pp [item bootstrap] | SE, items only | SE with run term |
|---|---:|---:|---:|
| `fable-5-1@high` - `opus-5-5@high` | 4.1 [1.9, 6.5] | 1.2 | 4.5 |
| `fable-5-1@high` - `haiku-5-5@high` | 5.1 [0.5, 9.1] | 1.8 | 4.5 |
| `haiku-5-5@high` - `opus-5-5@high` | -1.0 [-5.5, 3.9] | 2.0 | 4.4 |
| `opus-5-5@high` - `opus-5-5@medium` | 13.1 [10.2, 16.2] | 1.5 | 5.3 |
| `sonnet-5-5@high` - `sonnet-5-5@low` | 54.4 [47.5, 61.6] | 3.4 | 6.8 |

The run term counts each arm's effective runs (a partial replicate run counts
fractionally). The fable vs opus gap, clearly non-zero by its item interval, is within one
SE once runs are accounted for. The effort-level gaps stay clear: 13.1 pp is 2.5 SEs and
54.4 pp is 8 SEs.

## Validation

Monte Carlo checks of the planner (`results/validation/summary.md`; rates with exact 95%
Monte Carlo intervals there):

| Check | Quantity | Rate | Planner |
|---|---|---:|---:|
| paired t over items, 20 x 1 / 50 x 3 / 10 x 5 | size | 0.043 / 0.057 / 0.044 | 0.05 |
| same | power at planned MDE | 0.799 / 0.806 / 0.793 | 0.80 |
| run-aware t, 60 tasks, 3 runs | size | 0.077 [0.053, 0.108] | 0.05 |
| same | power at planned MDE | 0.775 [0.731, 0.815] | 0.80 |
| run-aware t, 60 tasks, 6 runs | size / power | 0.052 / 0.797 | 0.05 / 0.80 |
| run-blind paired t, 1 run, 120 / 30 tasks | false-positive rate | 0.615 / 0.370 | 0.624 / 0.368 |
| pass/fail (logistic), 50 x 3 / 30 x 1 | size | 0.060 / 0.044 | 0.05 |
| same | power at planned MDE | 0.854 / 0.866 | 0.80 |
| bootstrap, 40 tasks x 2 arms x 3 repeats | coverage: item / item x arm / within | 0.89 / 0.85 / 0.93 | 0.95 |
| bootstrap and chi-square, 60 tasks x 3 arms x 3 runs | coverage: item / item x arm / run | 0.93 / 0.94 / 0.96 | 0.95 |

Simulation counts: 2000 per power and false-positive check, 400 per run-aware check, 500
per pass/fail check, and 120 (200 bootstrap draws each) per coverage check. The unit tests
add unbiasedness checks of every estimator under every layout, the variance formula
against simulated experiments, and the REML code against statsmodels.

## Limitations

- **Few, similar datasets.** Four projects, one model family, one set of harnesses. Only
  mm-arena has replicate runs, and its run variance rests on 4 degrees of freedom; its
  interval spans a factor of six in SD.
- **Run effects may be version effects.** Runs 1 and 2 of mm-arena did not record the
  harness version; ruleproof's replicate runs used different hook builds. The model treats
  runs as exchangeable draws, which a one-off version change is not.
- **Lower bounds where runs are not replicated.** Every MDE for agent-ab, overclaim and
  ruleproof-pressure assumes no run effect.
- **Linear model for pass/fail outcomes, with common variances across arms.** The
  simulation checks show this is conservative for planning, but component estimates near
  0% or 100% pass rates sit on the boundary.
- **Interval methods.** The percentile bootstrap undercovered the item x arm SD with 40
  items (0.85); the run-variance interval treats the residual as known; the run-aware
  t-test was liberal with three runs per arm (size 0.077).
- **Quick profile.** 1000 bootstrap draws per dataset and the Monte Carlo sizes above. A
  full-profile run (10,000 draws, about 10x the simulations) is prepared but not yet run.
- **Data snapshot.** The mm-arena replicate runs were incomplete at extraction; rerunning
  `evalnoise extract` and `evalnoise study` when they finish will change the mm-arena rows.

## Reproduce

```sh
uv sync --group dev
uv run evalnoise study --profile quick      # results/study/
uv run evalnoise validate --profile quick   # results/validation/
# regenerate results/trials/ from source checkouts next to this repository:
uv run evalnoise extract
```
