# evalnoise report: variance components of four Claude agent evals

Quick profile, 2026-10-30. All numbers come from `results/study/summary.md` and
`results/validation/summary.md` (or the unit files next to them), which
`uv run evalnoise study` and `uv run evalnoise validate` regenerate (about 4 minutes each
on a laptop CPU), except the few marked as derived, which
`uv run python scripts/derived_numbers.py` prints. Intervals are 95%. Model, estimators and interval methods: [docs/DESIGN.md](docs/DESIGN.md).

## Summary

- In mm-arena, the only dataset with replicate runs of unchanged setups (four Claude
  setups at high effort run two to four times on all 120 episodes; ruleproof's replicate
  runs changed the hook build), the run SD pooled over the four setups was **2.9 pp** of
  edge captured (**1.6 to 6.4**, chi-square, 7 df). Most of it is one setup: fitted alone,
  the run SDs are 1.3 (`fable-5-1@high`), 1.7 (`opus-5-5@high`), 1.5 (`sonnet-5-5@high`)
  and 4.0 (`haiku-5-5@high`, four runs), and re-estimated without haiku the run SD is 1.6
  (0.5 to 5.2). The setups also differ in item x run SD (7.6, 10.8, 13.2 and 18.3;
  Bartlett p < 0.001, though heavy-tailed residuals make that p too small), so the
  shared-variance model is a rough approximation here. Run shifts were not uniform across
  the five task families either (haiku r1 to r2: +1.7 to +22.8 pp by family, median
  episode shift +2.3 against a mean of +10.5), so part of the run term may be a family x
  run effect, which more families would shrink.
- **Within one harness version, the one pair available shows no run effect beyond episode
  noise.** Haiku runs 3 and 4 used the same Claude Code version (2.1.308, recorded in the
  traces) on the same day; their means differ by 1.4 pp (median episode shift 0.0).
  Refitted on those two runs alone, the run variance estimate is negative (upper end of
  the run SD interval 31.5 pp on 1 df, derived), against a run SD of 4.0 [1.8, 16.2] over
  all four haiku runs, whose versions differ (runs 1 and 2 did not record theirs). This
  fits the haiku run term coming mostly from version or date changes, but one pair on
  1 df cannot show it: the model has no harness factor, so the study's run term still
  mixes both.
- For a hypothetical pair of setups with the pooled variances, compared from one run
  each, the estimated SE of the difference is **4.7 pp** instead of the **2.3 pp** the
  episodes alone give (2.6, derived, once the two seeds of a game are treated as correlated
  via the median design effect of 1.24); the run term is 76% of the variance (treating
  episodes as independent; with their clustering the item part is larger, so 76% and the
  rate below are upper-end figures). A paired test over episodes, which ignores runs,
  would call two setups with equal mean scores different **33%** of the time (**17% to
  62%** across the run-variance interval) at a nominal 5%; for literally identical setups,
  whose item x arm effects cancel, the rate is higher (41%, derived). Fitted without the
  haiku setup (fable, opus and sonnet; every component re-estimated), the SE is 3.0 pp and
  the rate 19% (derived).
- With the pooled estimates no number of episodes brings the MDE of a one-run-per-setup
  comparison below 10 pp. 10 pp needs 3 runs per setup with 56 episodes or 4 with 41
  (2 runs need 157, more than the 120 available). 5 pp needs at least 6 runs (13759
  episodes); 8 runs need 297, 10 runs 188 and 20 runs 107. These counts treat episodes as
  independent; the seeds of a game are correlated (design effect about 1.24), so multiply
  them by at least 1.24, which puts 20 runs at 5 pp (133) beyond the 120 episodes
  available while 3 runs at 10 pp (69) still fit. Episodes of one
  task family are more alike still (family-clustered design effect about 2.4 over pairs,
  from only 5 families), and "only runs help" assumes run shifts shared by every
  episode, which the family breakdown contradicts. The run-variance interval is wide, so
  the counts are uncertain by a factor of several.
- In the pass/fail datasets with one run per arm (agent-ab, overclaim, ruleproof
  pressure), the run variance is not identified. Their MDEs at the published designs,
  6.6 pp (agent-ab, 50 tasks x 3), 11 pp (overclaim, 23 x 2 and 18 x 4) and 53 pp
  (ruleproof pressure, 5 tasks x 3), assume no run effect, which understates them if runs
  vary; the linear model for pass/fail scores can also bias them either way (conservative
  at 60 to 70% pass and for gains near the ceiling, optimistic for losses near it). Trial
  noise within a run was SD 18 to 22 pp of pass rate (36 pp on ruleproof's pressure
  tasks), far larger than the item x arm SD, so repeats there buy real precision. Most of
  these pairs differ on fewer than 10 tasks (agent-ab Haiku vs Sonnet: 3 of 50), so their
  SEs and MDEs rest on a handful of tasks.
- The planner reproduces its nominal power and size in simulation when its assumptions
  hold. Known gaps: the run-aware t-test is somewhat liberal with three runs per arm;
  with the run variance borrowed from a pilot with 4 run df (mm-arena's MDEs now borrow
  7), power at the planned MDE was 0.76; near a 90% pass rate the planned MDE is conservative for
  gains but optimistic for losses (power 0.67); and the percentile bootstrap undercovers
  the item x arm SD (and slightly the item SD) with 40 items and the item x run SD
  (0.88, as reported for mm-arena's 14.5 [11.1, 17.7]) with 60 items and 3 runs.

These are nine analyses of seven tables from four small projects, all using Claude models
through Claude Code or the Claude CLI. They show what the method finds; they do not
establish how large run effects are for agent evals in general.

## Data

| Dataset | Source | Arms | Items | Runs per arm | Repeats | Trials | Score |
|---|---|---:|---:|---|---:|---:|---|
| `mm-arena-replicated` | [mm-arena](https://github.com/h-a-forster/mm-arena) core-v1 | 4 | 120 | 2-4 | 1 | 1320 | edge captured, pp |
| `mm-arena-all` | same, all 9 LLM setups | 9 | 120 | 1-4 | 1 | 1920 | edge captured, pp |
| `agent-ab-no-tests` | [agent-ab](https://github.com/h-a-forster/agent-ab) | 2 | 50 | 1 | 3 | 300 | passed, pp |
| `agent-ab-no-tests-cost` | same | 2 | 50 | 1 | 3 | 300 | log cost (log USD) |
| `agent-ab-haiku-vs-sonnet` | same | 2 | 50 | 1 | 1 | 100 | passed, pp |
| `overclaim-setups` | [overclaim](https://github.com/h-a-forster/overclaim) study 1 | 4 | 23 | 1 | 2 | 184 | passed, pp |
| `overclaim-interventions` | overclaim study 2 | 4 | 18 | 1 | 4 | 288 | passed, pp |
| `ruleproof-main` | [ruleproof](https://github.com/h-a-forster/ruleproof) bench | 9 | 5 | 1-2 | 3 | 180 | all rules followed, pp |
| `ruleproof-pressure` | ruleproof pressure tasks | 6 | 5 | 1 | 3 | 80 | all rules followed, pp |

mm-arena episodes are items and games are bootstrap clusters (each game has two seeds that
share a hidden structure). Every mm-arena run is complete (120 episodes) and read from
mm-arena's `results/core-v1`, where all replicate runs are now committed (on its branch
`polish-2026-10-30`, not yet merged into the public main branch);
`results/trials/MANIFEST.json` records that commit and each file's sha256. The table's
`harness` column carries the Claude Code version from each trace's provenance: 2.1.308
for fable r2, haiku r3 and r4, opus r3 and sonnet r2; runs 1 and 2 did not record it
(mm-arena's README gives 2.1.296 for opus and haiku r2 and an earlier version for r1). In ruleproof, the replicate runs of the three hook arms used different hook builds,
so their run term includes a code change.

## Variance components

SD in the dataset's unit; 95% cluster-bootstrap intervals, chi-square for run.
`n/i`: not identified; `(in X)`: folded into X; `<0`: negative moment estimate (0 in
planning); `upper bound < 0`: the upper end of its bootstrap interval is negative too. ICC item is the
correlation between trials of two different arms on the same item.

| Dataset | item | item x arm | run | item x run | within run | ICC item |
|---|---:|---:|---:|---:|---:|---:|
| `mm-arena-replicated` | 51.6 [38.3, 63.0] | 10.6 [7.4, 13.3] | 2.9 [1.6, 6.4] | 14.5 [11.1, 17.7] | (in item x run) | 0.89 |
| `mm-arena-all` | 43.4 [32.9, 52.6] | 19.2 [16.2, 22.0] | 2.9 [1.6, 6.4] | 14.5 [11.2, 17.6] | (in item x run) | 0.76 |
| `agent-ab-no-tests` | 13.9 [0.0, 24.3] | 3.2 [0.0, 8.7] | n/i | (in item x arm) | 19.1 [12.9, 23.8] | 0.34 |
| `agent-ab-no-tests-cost` | 0.753 [0.489, 0.993] | 0.166 [0.027, 0.258] | n/i | (in item x arm) | 0.191 [0.140, 0.245] | 0.90 |
| `agent-ab-haiku-vs-sonnet` | 13.4 [0.0, 23.7] | 17.4 [0.0, 26.4] | n/i | (in item x arm) | (in item x arm) | 0.37 |
| `overclaim-setups` | 43.0 [27.8, 49.1] | <0 [0.0, 1.3] | n/i | (in item x arm) | 18.1 [10.4, 25.5] | 0.85 |
| `overclaim-interventions` | 22.8 [0.6, 37.1] | <0 [upper bound < 0] | n/i | (in item x arm) | 22.3 [14.8, 28.7] | 0.51 |
| `ruleproof-main` | 9.5 [0.0, 12.0] | 19.6 [10.6, 21.3] | <0 [0.0, 8.8] | <0 [0.0, 7.5] | 22.4 [18.3, 25.8] | 0.09 |
| `ruleproof-pressure` | 26.2 [0.0, 35.9] | 7.5 [0.0, 14.8] | n/i | (in item x arm) | 36.5 [20.0, 47.6] | 0.33 |

Observations:

- **mm-arena: per-episode scores vary hugely between episodes** (item SD 52 pp: an
  episode's edge relative to the suite-average Bayes edge), which is why the leaderboard
  number needs many episodes. This cancels in paired comparisons (ICC 0.89). What does not
  cancel is the run term and the item x run term (SD 14 pp per episode: the agent's own
  randomness plus item-specific changes between runs).
- **The run means move visibly** (`results/study/summary.md`, "Run shifts by family").
  `haiku-5-5@high` scored 79.9, 90.4, 83.2 and 84.6 in runs 1 to 4, `opus-5-5@high` 87.7,
  83.8 and 85.3, `fable-5-1@high` 90.7 and 88.6 and `sonnet-5-5@high` 69.2 and 71.9. Only
  haiku r3 and r4 share a recorded harness version; they differ by 1.4 (median episode
  shift 0.0), against 5.8 to 10.5 between haiku r2 and its other runs. The shifts are
  uneven across task families: `haiku-5-5@high` r1 to r2 moved +22.8 pp on cards and
  +1.7 on transform, and the median episode moved +2.3 against a mean of +10.5
  (`opus-5-5@high`: -0.4 against -3.9). Even r3 to r4 moved -8.9 on coin and +6.6 on dice
  while the mean moved +1.4. The model has no family x run term, so part of what it calls
  a run shift is family-specific.
- **The setups do not share one noise level.** Fitted one setup at a time
  (`results/study/summary.md`, "Run term by arm"), the run SD is 1.3 [0.0, 47.5] for
  `fable-5-1@high`, 1.7 [0.3, 12.4] for `opus-5-5@high`, 1.5 [0.0, 61.3] for
  `sonnet-5-5@high` and 4.0 [1.8, 16.2] for `haiku-5-5@high`, on 1 to 3 df; leaving one
  setup out gives 3.1, 3.3, 3.1 and 1.6. The item x run SD is 7.6, 10.8, 13.2 and 18.3
  (Bartlett p < 0.001; the residuals are heavy-tailed, which makes Bartlett's p too small,
  but a more than twofold spread in SD is large regardless). The pooled 2.9 pp and every
  number derived from it describe an average of these setups, not any particular pair.
- **`mm-arena-all` pools single-run setups** under the assumption that all setups share
  the replicated setups' residual; its larger item x arm SD (19.2 vs 10.6) reflects that
  low-effort setups disagree with high-effort ones on which episodes are hard.
- **Pass/fail data near ceiling** (agent-ab 93 to 95% pass, overclaim interventions 88
  to 92%) give wide item intervals that reach 0, and item x arm estimates at or below the
  boundary. In overclaim study 2 even the upper end of the item x arm bootstrap interval
  is negative, a hint that the moment noise model overstates the noise of the cell means
  there; with 3 to 5 tasks on which the arms differ, the draws resample the same few tasks.
  overclaim study 1 (pass rates 67 to 72%) has a much larger task SD (43 pp).
- **ruleproof has only 5 tasks**, so its item components are barely informative; its run
  estimate (hook arms, two builds) is 0 with an upper bound of 8.8 pp.
- **Cost** (agent-ab, log USD): tasks explain most of the variance (ICC 0.90); trial noise
  is SD 0.19 in log cost, about a 21% multiplicative spread.

### REML cross-check

The moment estimates agree with REML within their intervals. The largest difference is
`ruleproof-pressure` item x arm (7.5 vs 2.7 pp, interval 0 to 14.8; one arm has a single
repeat, so the layout is unbalanced); every other component differs by less than 2 pp
(`mm-arena-replicated` item x arm: 10.6 vs 10.7; `mm-arena-all` item: 43.4 vs 44.5). All pairs are in
`results/study/summary.md`.

## Planning

Paired comparison of two arms, one run per arm, at each dataset's observed number of tasks
and repeats. Where identified, the run variance is borrowed with its degrees of freedom
(7 for mm-arena), which widens the t quantiles. In simulation of a pilot with 4 run df
(`borrowed-t120-r1`) the test's size was 0.058 and its power at the planned MDE 0.76
(Monte Carlo interval 0.72 to 0.80), so the mm-arena MDEs may be slightly optimistic;
400 simulations cannot tell that power from 0.80, and the 7 df mm-arena now has were not
simulated. SEs are estimates; for mm-arena they rest on the 7 run df.

| Dataset | Tasks x repeats | SE, items only | SE with run term | MDE | MDE at run CI ends | Naive false-positive rate |
|---|---|---:|---:|---:|---:|---:|
| `mm-arena-replicated` | 120 x 1 | 2.3 | 4.7 | 14.4 | 9.5 to 29.7 | 33% [17%, 62%] |
| `mm-arena-all` | 120 x 1 | 3.1 | 5.1 | 15.3 | 11.1 to 30.1 | 24% [12%, 52%] |
| `agent-ab-no-tests` | 50 x 3 | 2.3 | n/i | 6.6 [4.7, 8.7] | - | n/i |
| `agent-ab-haiku-vs-sonnet` | 50 x 1 | 3.5 | n/i | 10.0 [0.0, 15.1] | - | n/i |
| `overclaim-setups` | 23 x 2 | 3.8 | n/i | 11.0 [6.4, 15.6] | - | n/i |
| `overclaim-interventions` | 18 x 4 | 3.7 | n/i | 11.1 [7.3, 14.2] | - | n/i |
| `ruleproof-main` | 5 x 3 | 14.9 | 14.9 | 55.9 [37.0, 59.8] | 55.9 to 63.3 | 5% [5%, 10%] |
| `ruleproof-pressure` | 5 x 3 | 14.1 | n/i | 53.2 [31.0, 65.7] | - | n/i |

MDE in pp, 80% power, alpha 0.05; brackets are item-bootstrap intervals (run variance held
at its estimate). For mm-arena the item-bootstrap interval is negligible next to the
run-variance interval, shown separately. Naive false-positive rate: how often a paired
test over items, which ignores runs, calls single runs of two setups with equal mean
scores different. It keeps the item x arm variance (the setups agree on average, not
episode by episode), so for `mm-arena-all`, whose item x arm SD reflects low- and
high-effort setups disagreeing, it is lower (24%) than for literally identical setups
(41% in both mm-arena rows, derived with item x arm set to 0).

Episodes per setup for a target MDE in `mm-arena-replicated` (R runs per setup, one
trial per episode per run; "never": the run term alone exceeds the target):

| Target | R1 | R2 | R3 | R4 | R5 | R6 | R8 | R10 | R15 | R20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 pp | never | 157 | 56 | 41 | 35 | 32 | 28 | 26 | 24 | 23 |
| 5 pp | never | never | never | never | never | 13759 | 297 | 188 | 126 | 107 |

Repeats within a run do not help here because within-run noise is not separated from
item x run noise (no repeats inside a run); the planner then assumes, conservatively, that
only new runs average it out. These counts treat the 120 episodes as independent; the
two seeds of a game are correlated, and the median design effect over pairs is 1.24, so
multiply them by at least 1.24. Clustered by task family the median design effect is 2.4
(5 families, so rough). They use the pooled components, which no single setup has.

Tasks per arm for the pass/fail datasets (no run effect assumed, and the linear model biases them either way near the pass-rate
bounds; K repeats per task):

| Dataset | Target | R1 K1 | R1 K3 | R3 K1 | R5 K1 |
|---|---:|---:|---:|---:|---:|
| `agent-ab-no-tests` | 5 pp | 239 | 86 | 86 | 55 |
| `agent-ab-no-tests` | 10 pp | 62 | 23 | 23 | 16 |
| `overclaim-interventions` | 10 pp | 81 | 29 | 29 | 18 |

Their arms differ on only 9 (agent-ab) and 3 to 5 (overclaim) tasks, so these counts are
rough.

## Pairwise differences, with and without the run term

For mm-arena, the item-level SEs understate the uncertainty of every pair:

| Pair (mm-arena) | Difference, pp [item bootstrap] | SE, episodes | SE, games | p, games | SE, families | SE with run term | df / p with run term | p, run variance without one setup |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `fable-5-1@high` - `opus-5-5@high` | 4.0 [1.8, 6.1] | 1.1 | 1.2 | <0.001 | 0.8 | 2.9 | 9.8 / 0.20 | 0.052 to 0.25 |
| `fable-5-1@high` - `haiku-5-5@high` | 5.1 [1.6, 8.6] | 1.6 | 1.7 | 0.005 | 2.9 | 3.1 | 14.9 / 0.12 | 0.030 to 0.16 |
| `haiku-5-5@high` - `opus-5-5@high` | -1.1 [-4.8, 2.9] | 1.7 | 2.0 | 0.60 | 3.2 | 3.0 | 21.5 / 0.73 | 0.65 to 0.74 |
| `opus-5-5@high` - `opus-5-5@medium` | 12.9 [10.2, 15.9] | 1.4 | 1.5 | <0.001 | 2.0 | 3.7 | 10.0 / 0.006 | <0.001 to 0.016 |
| `sonnet-5-5@high` - `sonnet-5-5@low` | 55.8 [49.2, 62.7] | 3.2 | 3.5 | <0.001 | 5.9 | 5.0 | 24.5 / <0.001 | <0.001 |

SE, games: clustered by game (60 games of two seeds each), tested with 59 df. SE,
families: clustered by task family; with 5 families it is rough, but for most pairs it is
well above the game-level SE (design effect about 2.4), so episodes are more dependent
than games alone suggest. The run term adds run / R per setup, R its number of runs (the
run-adjusted episode means average every run equally), and is tested with Satterthwaite
df using its own 7 df. The last column redoes that test with the run variance (and its
df) re-estimated without each replicated setup in turn; the pooled run variance comes
mostly from haiku (81% of the run sum of squares, derived), so this range is the honest
summary. The fable vs opus gap, clearly non-zero over games (p < 0.001), is not
distinguishable from zero once runs count (p from 0.052 to 0.25 depending on which
setups' run variance is assumed); fable vs haiku is borderline (0.030 to 0.16). The opus
effort gap, now tested with 7 run df, is significant under every choice (p from < 0.001
to 0.016, 0.006 pooled; it was borderline with 4); the sonnet effort gap stays clear. The
study also tests the three new pairs with `sonnet-5-5@high` (all p <= 0.003 with the run
term; `results/study/summary.md`). These run-aware tests are approximate: the setups do
not share one run variance.

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
| run-blind paired t, 1 run, 120 / 30 tasks | false-positive rate | 0.615 / 0.370 | 0.621 / 0.356 |
| pass/fail (logistic), 50 x 3 / 30 x 1, pass rate 60 to 70% | size | 0.060 / 0.044 | 0.05 |
| same | power at planned MDE | 0.854 / 0.866 | 0.80 |
| pass/fail near 90% pass, 50 x 3, gain / loss | size | 0.048 / 0.046 | 0.05 |
| same | power at planned MDE | 0.984 / 0.668 | 0.80 |
| run variance borrowed from a pilot (4 run df), 120 tasks, 1 run | size / power | 0.058 / 0.762 | 0.05 / 0.80 |
| bootstrap, 40 tasks x 2 arms x 3 repeats | coverage: item / item x arm / within | 0.89 / 0.85 / 0.93 | 0.95 |
| bootstrap and chi-square, 60 tasks x 3 arms x 3 runs | coverage: item / item x arm / item x run / run | 0.93 / 0.94 / 0.88 / 0.96 | 0.95 |

Simulation counts: 2000 per power and false-positive check, 400 per run-aware and
borrowed-run check, 500 per pass/fail check, and 120 (200 bootstrap draws each) per coverage check. The unit tests
add unbiasedness checks of every estimator under every layout, the variance formula
against simulated experiments, and the REML code against statsmodels.

## Limitations

- **Few, similar datasets.** Four projects, one model family, one set of harnesses. Only
  mm-arena has replicate runs of unchanged setups (ruleproof's replicates changed the
  hook build), and its run variance rests on 7 degrees of freedom; its
  interval spans a factor of four in SD.
- **Run effects may be version effects.** The model has no harness-version factor, so it
  cannot split the run term into version and within-version parts. In mm-arena runs 1
  and 2 did not record the harness version, and only one setup has two runs on one
  recorded version (haiku r3 and r4, which agree within episode noise; 1 df); ruleproof's
  replicate runs used different hook builds. The model treats runs as exchangeable draws,
  which a one-off version change is not.
- **No run effect where runs are not replicated.** Every MDE for agent-ab, overclaim and
  ruleproof-pressure assumes no run effect, which understates it if runs vary; the linear
  model can also move it either way (see the pass/fail item below).
- **Common variances across arms.** The mm-arena setups reject it (item x run SD 7.6 to
  18.3, run SD 1.3 to 4.0), and `mm-arena-all` extends the same assumption to five
  single-run setups. Pooled numbers describe an average setup.
- **Episodes are not independent.** mm-arena's two seeds per game are correlated, and
  episodes of one task family more so (design effect about 2.4 over pairs, from 5
  families). Pair tests use game-clustered SEs and report family-clustered ones, but the
  planner counts episodes as independent units, so its episode counts are at least 1.24x
  too small there. Run shifts differ by family, and the model has no family x run term:
  part of the run term may shrink with more families, which the planner does not credit.
- **Linear model for pass/fail outcomes.** At pass rates of 60 to 70% the planned MDE was
  conservative. Near 90% it was conservative for gains (power 0.98) and optimistic for
  losses (0.67), because the variance shrinks towards the ceiling; plan for a drop near 0%
  or 100% from the variance at the shifted rate. Component estimates near those rates sit
  on the boundary, and most pass/fail pairs here differ on fewer than 10 tasks.
- **Interval methods.** The percentile bootstrap undercovered the item x arm SD with 40
  items (0.85) and slightly the item SD (0.89), and the item x run SD with 60 items and
  3 runs (0.88); the run-variance interval treats the
  residual as known, pools arms whose residuals differ, is checked only in the balanced
  equal-variance case, is degenerate when runs agree more closely than the residual
  allows (two ruleproof hook arms fitted alone) and is not capped by the score range
  (its upper end for one ruleproof arm is 150 pp on a 0 to 100 scale); the residuals are heavy-tailed,
  so Bartlett's test overstates the evidence against equal item x run variances; the run-aware t-test was liberal with three runs per arm (size
  0.077), and with a run variance borrowed on 4 df its power at the planned MDE was 0.76.
- **Quick profile.** 1000 bootstrap draws per dataset and the Monte Carlo sizes above. A
  full-profile run (10,000 draws, about 10x the simulations) is prepared but not yet run.
- **Data snapshot.** The mm-arena rows use its runs as of 2026-10-30 (16 LLM runs);
  further replicate runs will change them (`evalnoise extract --only mm-arena`, then
  `evalnoise study`).

## Reproduce

```sh
uv sync --group dev
uv run evalnoise study --profile quick      # results/study/
uv run evalnoise validate --profile quick   # results/validation/
# regenerate results/trials/ from source checkouts next to this repository:
uv run evalnoise extract
```
