# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Study: per-arm run and item x run estimates, leave-one-arm-out run estimates and
  Bartlett's test of a common item x run variance; cluster-robust pair SEs with
  p-values, with and without the run term (Satterthwaite df); the median design effect
  of clustered items; a flag for pairs that differ on fewer than 10 items. The summary
  lists all planning notes.
- Validation: pass/fail checks near a 90% pass rate with gains and losses, and a check of
  tests that borrow the run variance from a small pilot; coverage of the item x run
  bootstrap interval.
- Study: an optional item family column (mm-arena: task family) adds family-clustered
  pair SEs, a family design effect and run shifts (run means, mean, median, by family)
  for every two runs of a replicated arm.
- Study: each pair's run-aware p-value with the run variance re-estimated without each
  replicated arm in turn.
- Summary: planning rows of datasets with a pair differing on fewer than 10 items are
  marked `(few)`.
- Planner: `design_effect` (multiplies the item-level variance; `power --design-effect`)
  and pass/fail planning (`pass_rate`, `pass_score`; `power --pass-rate --pass-score`):
  the shifted arm's variance is taken at its own pass rate where larger, and the MDE is
  the larger of gain and loss (`mde(direction=...)` gives one side).
- Study: a Brown-Forsythe test of equal item x run variances with items as units, next to
  Bartlett's; it now drives the planning note (mm-arena: p = 2.7e-07). `RunTerm` keeps
  each arm's full-fit residuals.
- Study: optional `bounds` per dataset (the pass/fail datasets: [0, 100]) caps the
  run-variance interval at (range / 2)^2 and marks 0/100 scores as pass/fail.
- Validation: `pairs-t120-mm`, an mm-arena-like layout (runs 2, 2, 2, 4, one half run,
  item x run variances 50 to 300): size of the study's run-aware pair test 0.062,
  run-interval coverage 0.950.
- `scripts/longrun.sh` (resumable full-profile launcher) and `scripts/derived_numbers.py`
  (the numbers REPORT.md marks as derived). The sdist now includes `configs/` and
  `uv.lock`.

### Changed

- The run-variance interval is the Burdick-Graybill modified large-sample (MLS) interval,
  which accounts for the residual's uncertainty (the chi-square interval treated it as
  known and undercovered with few residual df). mm-arena's intervals are unchanged to the
  shown digit; ruleproof-main's pooled upper end is 8.7 pp (was 8.8), and one ruleproof
  arm's upper end is capped at 50 pp (was 150 on a 0 to 100 scale).
- The study's tasks-needed tables multiply the item-level variance by the median game
  design effect over pairs (mm-arena-replicated 1.24): 10 pp needs 70 episodes with 3
  runs (was 56), 5 pp 133 with 20 runs (was 107).
- Pass/fail MDEs use the variance at the shifted rate where larger: agent-ab 8.3 pp (was
  6.6), overclaim 11.5 and 13.3 (were 11.0 and 11.1), ruleproof-main 63.2 (was 55.9).
  The near-90% loss check planned this way had power 0.788 (was 0.668 with the base-rate
  variance); each binary check is now planned for its own direction.
- `tests/test_validation_slow.py` allows 3 Monte Carlo SEs (was a slack of 0.12 for
  coverage and pass/fail checks) and lists the known gaps by name and direction.
- Study `SCHEMA` 8, validation `SCHEMA` 5.

- Data: the mm-arena table now holds every replicate run, complete (fable r2, haiku r3 and
  r4, opus r3, sonnet r2; 1920 trials), read from mm-arena's `results/core-v1` only. The
  quick study and REPORT.md follow: pooled run SD 2.9 pp [1.6, 6.4] on 7 df (was 4.2 on
  4), naive false-positive rate 33% (was 50%), one-run MDE 14.4 pp (was 21.9).
- Validation: the borrowed-run check simulates a 7-df pilot (7 arms x 2 runs), the df
  mm-arena's MDEs borrow (was 2 arms x 3 runs, 4 df): size 0.068, power 0.795 at the
  planned MDE (was 0.058 and 0.762 on 4 df).
- Source-file sha256 values in `MANIFEST.json` are taken with CRLF read as LF, so a CRLF
  and an LF checkout of a source repository give the same digests.
- `scripts/derived_numbers.py` also refits each setup's run term on its runs that share a
  recorded harness version (haiku r3 and r4 on Claude Code 2.1.308).
- The mm-arena planning grid covers every run count where the plan changes (1 to 20).
- Negative moment estimates are shown as `<0` in the study summary instead of 0; the
  label for a negative bootstrap upper bound says `upper bound < 0` (it was `all draws <
  0`, which the test did not check).

### Fixed

- Planning took an omitted item x run or within-run variance as 0 (for example
  `power --components item_arm=70,run=17`); it is now an error unless the layout folded
  that component into another.
- `Components.from_dict` could not read the nulls that study unit files use for nan.
- A test depended on a scipy release in which `nct.cdf` returns nan.
- The run-aware pair test counted a partial replicate run fractionally; the run-adjusted
  item means weight every run equally, so it now adds run / R with R the number of runs.
- The run chi-square interval returned a zero-width [0, 0] when even its upper end fell
  below zero; it is now reported as degenerate.
- The naive false-positive rate used a normal critical value for what is a t-test over
  items, overstating it with few tasks (mm-arena: 51% is now 50%).
- `power --task-cost` ignored `--runs`; it now reports the optimal repeats per run count.
- `evalnoise extract` wrote earlier CSVs before a later table failed, leaving the
  manifest stale; malformed source records raised raw tracebacks; mm-arena `prior_std`
  of 0 was silently replaced by 1.
- Study dataset ids and table names could point outside the output directory.
- The within-cell sum of squares lost precision on large scores (one-pass formula).
- `.eval` logs now reach the Inspect reader's "convert first" message; several run-less
  table files sharing an arm are refused instead of merged into one run; Inspect samples
  skipped for errors are counted and reported.

## [0.1.0] - 2026-10-30

### Added

- Trial-table loader and validator (CSV, JSON Lines) with column mapping; adapters for
  Inspect JSON logs and lm-eval `samples_*.jsonl` files.
- Moment estimators of five variance components (item, item x arm, run, item x run,
  within run) with explicit handling of what each layout can identify; cluster bootstrap
  intervals; a chi-square interval for the run variance; a dense REML cross-check.
- Planner: variance of a paired or unpaired difference, MDE (normal or Satterthwaite t),
  tasks needed for a target MDE, naive false-positive rate of run-blind tests, and
  cost-optimal repeats.
- `evalnoise components | power | extract | study | validate` commands; resumable study and
  Monte Carlo validation with per-unit checkpoints.
- Per-trial tables from mm-arena, agent-ab, overclaim and ruleproof, the quick study
  results and the quick validation results.
