# evalnoise design

This document fixes the model, the estimands, the estimators, what each data layout can
identify, how intervals are formed, the planning formulas and how they are validated. It
also lists prior work and how evalnoise relates to it.

## 1. Problem

Agent evals are usually compared from one run per configuration. A run's score moves for
three different reasons: which tasks were sampled, the agent's own randomness on each
task, and shocks shared by a whole run (a different CLI or API version, server-side
changes, time of day, a harness bug fixed between runs). Item-level confidence intervals,
including clustered and paired ones, see only the first two. evalnoise estimates all
three from per-trial data and turns them into a plan: how many tasks, repeats and runs a
comparison needs to detect a given difference.

## 2. Model

For the score `y` of arm `a` (a model, prompt, harness or other configuration) on item `i`
(a task or benchmark item), in run `r` of that arm, repeat `k`:

```
y_airk = mu_a + u_i + v_ai + w_ar + g_air + e_airk
```

| Term | Variance | Meaning |
|---|---|---|
| `u_i` | `item` | how hard item `i` is for every arm |
| `v_ai` | `item_arm` | how much harder or easier item `i` is for arm `a` than the item effect says |
| `w_ar` | `run` | a shift shared by every trial of one run of one arm |
| `g_air` | `item_run` | item-specific change between runs (not shared within a run) |
| `e_airk` | `within` | trial-to-trial noise inside one run |

All effects are independent with mean zero, and the variances are common to all arms
(a working assumption: the study reports per-arm run and item x run estimates, run
estimates leaving each arm out, and Bartlett's test that the arms share one item x run
variance). There is no term for groups of items above the cluster: if a run shifts some
task families more than others, the model reads part of that family x run effect as `run`,
which would shrink with more families but not with more items per family. Where a table
names item families the study reports family-clustered pair SEs and run shifts by family.
Runs are nested in arms:
run `r1` of arm A has nothing to do with run `r1` of arm B. Scores are analysed on their own
scale; pass/fail outcomes are 0/1 (or 0/100 for percentage points), which makes the
components variances of a linear probability model. That is the right scale for the
variance of a mean difference, which is all the planner needs; section 7 checks it on
simulated binary data.

## 3. Estimands

- The five variance components above, reported as standard deviations in the score's
  unit, with 95% intervals.
- `ICC item = item / (item + item_arm + run + item_run + within)`: the correlation between
  trials of two different arms on the same item. It ranges from 0.09 (`ruleproof-main`) to
  0.90 (`agent-ab-no-tests-cost`; 0.89 for `mm-arena-replicated`) here; where it is large,
  paired comparisons are much more efficient than unpaired ones.
- For a comparison of two arms on `T` items with `R` runs per arm and `K` repeats per item
  per run, the variance of the difference in arm means:

```
paired:    V = 2 (item_arm + item_run / R + within / (R K)) / T  +  2 run / R
unpaired:  V = 2 (item + item_arm + item_run / R + within / (R K)) / T  +  2 run / R
```

- The minimum detectable effect (MDE): the smallest true difference detected with
  probability `power` by a two-sided level-`alpha` test.
- The naive false-positive rate: how often a test that estimates only the item-level part
  of `V` (here a paired t-test over items) declares a
  difference between two arms with equal mean scores, when each arm has `R` runs:
  `2 (1 - F_nu(t_{nu,1-alpha/2} sqrt(V_items / (V_items + V_run))))`, with `F_nu` the t
  distribution on the test's `nu = T - 1` df (paired; `2 (T - 1)` unpaired): the test
  statistic is `sqrt((V_items + V_run) / V_items)` times a central t. `V_items` keeps
  `item_arm`: the arms agree on average but not item by item. For two literally identical
  arms `item_arm` is 0 and the rate is higher. A cluster-robust test that ignores runs has
  the same form with its own `V_items` and `nu` = clusters - 1.

The run term has no `T` in its denominator: more tasks or repeats never remove it. Only
more runs per arm do, or a design in which both arms share each run's shock (for example
interleaving arms within one batch), which this model does not assume.

## 4. Identification

What a table can separate depends on its layout:

| Layout | Identified | Folded together |
|---|---|---|
| repeats within runs and replicate runs | all five | none |
| replicate runs, one trial per item per run | `item`, `item_arm`, `run`, `item_run + within` | `within` into `item_run` |
| repeats within one run per arm | `item`, `item_arm + item_run`, `within` | `item_run` into `item_arm`; `run` not identified |
| one trial per item per arm | `item`, `item_arm + item_run + within` | both residual parts into `item_arm`; `run` not identified |
| one arm | `item + item_arm` | `item_arm` into `item` |

The `absorbed` field of every estimate records what was folded where. The planner then
handles each case conservatively: a folded component is put where it does not shrink with
the planned repeats or runs, so the reported MDE is never smaller than the model implies.
The run variance is the exception: without replicate runs it is simply unknown, and the
planner refuses to guess. The user must pass it (`--run-var`, possibly from another
dataset) or explicitly assume zero, and the study says every such MDE assumes no run
effect (it understates the MDE if runs vary).

## 5. Estimators

**Moment estimators** (`evalnoise.components.estimate`), unbiased under the model:

1. `within`: pooled within-cell variance over (arm, run, item) cells with two or more trials.
2. `run` and the cell-level residual: for each arm with two or more runs, an item + run
   fixed-effects fit to cell means (Henderson's method III). `SS(run | item)` has
   expectation `df_run s2_cell + k run` with `k = trace(Z'(I - P_item) Z)`, computed
   exactly for unbalanced layouts, so partially finished runs are used correctly. Sums of
   squares, degrees of freedom and `k` are pooled over arms. `item_run` is the cell-level
   residual minus `within / n_h` (harmonic mean trials per cell).
3. `item` and `item_arm`: cell means are adjusted by the fitted run effects, averaged to one
   mean per (arm, item), and a two-way ANOVA (arms x items, items shared by all arms) gives
   `E[MS_inter] = item_arm + noise` and `E[MS_item] = A item + item_arm + noise`, where
   `noise` is the mean variance of the (arm, item) means implied by steps 1-2.
4. Pairs: for each requested pair the per-item differences give the mean difference, its
   items-only SE, a cluster-robust SE (sums of centred differences per cluster; equal to
   the items-only SE with one item per cluster), the number of items on which the arms
   differ, and the pair's own `item_arm` (half the excess variance of the differences).
   The study tests each pair over clusters (clusters - 1 df) and, adding `run / R` per arm
   (`R` its number of runs: the run-adjusted item means average every run's shock equally,
   so a partial run counts as a whole one), with Satterthwaite df using the run term's own
   df; and again with the run variance re-estimated without each replicated arm. It also
   reports the median design effect (clustered over items-only SE, squared), the same for
   item families where the table names them, and flags pairs that differ on fewer than 10
   items.

**REML** (`evalnoise.reml`): the same model fitted by restricted maximum likelihood with a
dense marginal covariance and analytic gradients (L-BFGS-B), as a cross-check. On balanced
data with interior estimates REML and the moment estimators coincide; the tests check this,
and check the REML code against statsmodels' MixedLM on small unbalanced tables.
statsmodels itself is not used at runtime: its single-group crossed fit did not finish
within two minutes on a simulated 720-trial table (40 items, 3 arms, 3 runs, 2 repeats)
that the dense fit handles in about 5 seconds.

Negative moment estimates are kept for bootstrapping, used as 0 in planning and shown as
`<0` in the study summary.

## 6. Intervals

- Item-level components (`item`, `item_arm`, `item_run`, `within`) and pairwise
  differences: percentile bootstrap over clusters (items by default; games in mm-arena,
  whose two seeds share a hidden structure). Duplicated clusters become distinct items.
  Runs are not resampled.
- `run`: a chi-square interval from `SS(run | item) / E[MS] ~ chi2(df) / df`, treating the
  cell-level residual as known (it has hundreds of degrees of freedom where the run term
  has a handful). With `df` pooled runs-minus-one, the interval is honest about how little
  two or three runs say: its upper end is often several times the estimate.
- MDE: the study reports the MDE with the run variance at its estimate, a bootstrap
  interval over the item-level components, and the MDE at both ends of the run interval.

## 7. Planning and validation

`evalnoise.power` computes `V`, the MDE (normal, or t with Satterthwaite degrees of
freedom: `T - 1` for the paired item term, `2 (R - 1) + run_df` for the run term, where
`run_df` is the degrees of freedom of a run-variance estimate borrowed from a pilot; the
study borrows its own pooled run degrees of freedom, and a run variance passed by hand is
treated as known, `run_df = inf`), the fewest tasks for a target MDE (`None` when the run
term alone exceeds it), the naive false-positive rate, and the cost-optimal number of
repeats

```
K* = sqrt(task_cost within / (R (R item_arm + item_run)))
```

where `task_cost` is the cost of adding a task to one arm in units of one trial. With
`task_cost = 0` (the tasks exist already) the answer is one repeat: a new task always buys
more precision than another repeat of an old one.

`evalnoise validate` runs Monte Carlo checks (results in `results/validation/`):

| Check | Data | Analysis | Should match |
|---|---|---|---|
| `power-*` | Gaussian, no run effect | paired t-test over items | alpha at 0; 80% at the MDE |
| `runs-*` | Gaussian, run effect, 3 or 6 runs | moment estimates + Satterthwaite t | alpha at 0; 80% at the MDE |
| `naive-*` | Gaussian, run effect, 1 run | paired t-test over items | the naive false-positive rate |
| `binary-*` | logistic pass/fail, 60 to 70% and 90% pass, gains and losses | paired t-test over items, planned from a pilot | alpha at 0; 80% at the MDE |
| `borrowed-*` | Gaussian, run effect, 1 run per arm | run variance from a 4-df pilot + Satterthwaite t | alpha at 0; 80% at the MDE |
| `coverage-*` | Gaussian | bootstrap / chi-square intervals | 95% coverage |

The unit tests also check unbiasedness of every estimator for every layout in section 4,
the variance formula against simulated experiments, and the planner's root-finding.

## 8. Data

`evalnoise extract` rebuilds `results/trials/*.csv` from the published result directories
of four studies, all run with Claude models through Claude Code or the Claude CLI
(`configs/sources.toml`). `MANIFEST.json` records each source's repository, commit,
per-file sha256 and any source files not tracked by the source repository's git.

| Table | Score | Item / cluster | Runs |
|---|---|---|---|
| `mm-arena` | edge captured, pp: `100 xpnl_sd / mean(bayes xpnl_sd)`, so an arm's mean over the suite is its leaderboard number | episode (game, seed) / game | replicate runs `#rN` of four setups; harness version per run from trace provenance where recorded |
| `agent-ab-*` | hidden check passed (0/1); `log_cost` | task | one run per arm |
| `overclaim-*` | hidden check passed (0/1) | task | one run per arm |
| `ruleproof-*` | all rules followed (0/1) | task | hook arms run twice (`p2`, `p3`), on different hook builds |

Trials without a verdict (agent errors) are excluded and counted in the manifest.

## 9. Prior art

- Evan Miller, "Adding Error Bars to Evals: A Statistical Approach to Language Model
  Evaluations", 2024. <https://arxiv.org/abs/2411.00640>. Clustered standard errors,
  paired differences, resampling each question to cut within-question variance, and power
  analysis. evalnoise's `item_arm` and `within` terms are his per-question and resampling
  variances; it adds the run term, which item-level formulas cannot see, and estimates the
  components from real agent data rather than assuming them.
- Bjarni Haukur Bjarnason, André Silva, Martin Monperrus, "On Randomness in Agentic
  Evals", 2026. <https://arxiv.org/abs/2602.07150>. About 60,000 SWE-Bench-Verified
  trajectories: single-run pass@1 moves by 2.2 to 6.0 points between runs; recommends
  several runs per task and power analysis. No code is linked from the paper page.
  evalnoise provides the decomposition and the planner, for any score type.
- Shreyas K Chandrahas, "evalci: A Python Library for Statistically Rigorous Comparison of
  Language Model Evaluations", 2026. <https://arxiv.org/abs/2607.04429>,
  <https://github.com/Shreyaskc/evalci>. Confidence intervals, paired tests, power and
  multiple-comparison correction for static QA benchmarks (lm-eval and HELM adapters).
  It treats items as the only random factor; evalnoise targets agent evals with repeats
  and runs.
- Solomon Messing, "Hidden Measurement Error in LLM Pipelines Distorts Annotation,
  Evaluation, and Benchmarking", 2026. <https://arxiv.org/abs/2604.11581>. Naive standard
  errors miss variance from judge, temperature and prompt choices and undercover more as
  n grows; a pilot can project which design change buys the most precision. The run term
  here is one such source, and the planner is that kind of projection.
- Yunbei Zhang et al., "Stop Comparing LLM Agents Without Disclosing the Harness", 2026.
  <https://arxiv.org/abs/2605.23950>. Harness-induced variance can exceed model-induced
  variance; proposes disclosure and a variance-decomposition protocol. In the data here,
  harness version is recorded only for newer mm-arena runs and is confounded with run;
  one setup has two runs on one recorded version, too few for a harness factor.
- Variance-component methods: S. R. Searle, G. Casella, C. E. McCulloch, *Variance
  Components* (Wiley, 1992), for Henderson's method III and REML; R. K. Burdick and
  F. A. Graybill, *Confidence Intervals on Variance Components* (Dekker, 1992); F. E.
  Satterthwaite, "An approximate distribution of estimates of variance components",
  *Biometrics Bulletin* 2(6), 1946.

## 10. Limitations of the design

- Common variances across arms. Pass/fail data violate this (variance `p(1 - p)`): near
  the ceiling a planned drop is detected less often than planned and a gain more often
  (see the binary checks). The mm-arena setups violate it too (item x run SD 7.6 to 18.3).
- Items are independent in the planner. Clustered items (mm-arena's seeds within games,
  and its task families) make its task counts too small by the design effect, which the
  study reports.
- MDEs with a run variance borrowed on few df may be slightly optimistic (power 0.76 at a
  planned 0.80 with 4 df; Monte Carlo interval 0.72 to 0.80 at 400 simulations, so not
  distinguishable from 0.80).
- Runs are assumed exchangeable. A run effect that is really a version change (a harness
  update between runs) is a fixed shift, not a draw from a distribution; the model treats
  it as random because nothing records which runs share a version.
- Normal-theory intervals for the run variance, with very few degrees of freedom. The
  chi-square interval treats the residual as known; it is degenerate (reported as such)
  when the runs agree more closely than the residual allows, and its upper end is not
  capped at the largest SD a bounded score allows.
- The percentile bootstrap undercovers for variance components with few items (see
  `results/validation/`).
