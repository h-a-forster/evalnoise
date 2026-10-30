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
- `scripts/longrun.sh` (resumable full-profile launcher) and `scripts/derived_numbers.py`
  (the numbers REPORT.md marks as derived). The sdist now includes `configs/` and
  `uv.lock`.

### Changed

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
