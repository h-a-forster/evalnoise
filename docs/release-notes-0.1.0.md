# evalnoise 0.1.0 release notes

First release. It covers the `[0.1.0]` and `[Unreleased]` sections of
[CHANGELOG.md](../CHANGELOG.md); numbers below come from [REPORT.md](../REPORT.md) (quick
profile) and trace to `results/study/summary.md`, `results/validation/summary.md` or
`scripts/derived_numbers.py`.

## Changes since the 2026-10-30 draft of these notes

- `power` refuses `--pass-score` without `--pass-rate`, and `resolve` refuses pass/fail
  planning when the variances are too large for the pass score (percentage-point variances
  with the default score used to give the base-rate MDE with no warning).
- Trial tables refuse two rows with the same arm, run, item and repeat, and the CLI
  validates the table merged from several files (duplicates read as repeats that agree
  exactly, and an item could sit in two clusters).
- `study` no longer stops when a bootstrap draw misses the few repeated or replicated items.
- `mde` says so when power does not exceed alpha, instead of a root-finder error.
- The REML cross-check, and so `study` and `components --reml`, works on pandas 2, which
  the declared `pandas>=2.1` allows; CI now also tests the lowest declared dependencies.
- Validation units are valid JSON (no `NaN`), and a new check records the power of a loss
  near 90% pass planned from the base-rate variance.
- REPORT.md gives the item SDs and MDEs without tasks no trial passed, and the agents'
  setups. `backlog.md` replaces the status section of `AGENTS.md`.

## What it does

evalnoise splits the variance of per-trial agent-eval scores into item, item x arm, run,
item x run and within-run parts, says which parts a layout cannot separate, gives each an
interval, and plans comparisons: the minimum detectable effect (MDE) of a design, the tasks
needed for a target MDE, and the false-positive rate of tests that ignore run effects.
Python 3.11+, numpy, scipy and pandas only; no model or network calls.

## In this release

- Estimators: Henderson method III for the run term and two-way ANOVA for item terms,
  with a dense REML cross-check; cluster-bootstrap intervals for item-level components;
  the Burdick-Graybill modified large-sample (MLS) interval for the run variance, capped
  at `(range / 2)^2` for bounded scores.
- Planner: paired or unpaired designs with runs and repeats, Satterthwaite t with the run
  variance's own degrees of freedom (borrowed from a pilot if needed), an optional design
  effect for clustered items, and pass/fail planning that takes the shifted arm's variance
  at its own pass rate where larger (the MDE is the larger of gain and loss).
- CLI: `evalnoise components | power | extract | study | validate`; the study and the
  Monte Carlo validation are resumable, one checkpoint per unit or shard.
- Data and results: per-trial tables from four Claude-only projects (mm-arena, agent-ab,
  overclaim, ruleproof), the quick study over nine analyses, and the quick validation.
- Diagnostics in the study: per-arm run terms, leave-one-arm-out run estimates, Bartlett
  and item-level Brown-Forsythe tests of equal item x run variances, cluster- and
  family-clustered pair SEs, run-aware pair tests, run shifts by task family.

## Headline results (quick profile)

- mm-arena, the only dataset with replicate runs of unchanged setups: pooled run SD
  2.9 pp of edge captured [1.6, 6.4] on 7 df, mostly from one setup; for a one-run
  comparison the SE is 4.7 pp instead of the 2.3 pp episodes alone give, and a run-blind
  paired test calls setups with equal means different 33% of the time [17%, 62%].
- 10 pp between two mm-arena setups needs 3 runs with 70 episodes each (game design effect
  1.24 included); 5 pp needs 20 runs with 133 episodes, more than the 120 available.
- Pass/fail datasets with one run per arm cannot identify the run term; their MDEs
  without one are 8.3 pp (agent-ab, 50 tasks x 3) and 11.5 and 13.3 pp (overclaim).

These are a handful of small Claude-only datasets; they show what the method finds, not
how large run effects are for agent evals in general.

## Validation

In simulation the planner's size and power match nominal where its assumptions hold
(paired t over items: size 0.043 to 0.057, power 0.793 to 0.806). Planned from the
variance at the shifted rate, a loss near a 90% pass rate was detected with power 0.788
(0.708 from the base-rate variance, in the committed `binary-p90-t50-k3-down-base` check;
the 0.67 in the changelog came from an earlier trial run).
In an mm-arena-like layout the study's run-aware pair test had size 0.062 and the MLS run
interval covered 0.950. Known gaps, named in `tests/test_validation_slow.py`: the
run-aware t-test is somewhat liberal with three runs (size 0.077) and with a run variance
borrowed on 7 df (0.068); pass/fail planning is conservative at 60 to 70% pass and for
gains near the ceiling; the percentile bootstrap undercovers item x arm with 40 items
(0.85) and item x run with 60 items and 3 runs (0.875).

## Known limitations

- Variances are common to all arms in the model; mm-arena's setups reject that
  (Brown-Forsythe p = 2.7e-07). No harness-version factor and no family x run component.
- The planning grid and one-run MDEs count items as independent; only the tasks-needed
  tables apply the game design effect.
- Full-profile runs (10,000 bootstrap draws, about 10x the simulations) are prepared but
  not yet run; see `backlog.md` for the remaining next steps.
- The pass/fail tables keep tasks no trial passed, which make up most of their item SDs
  (REPORT.md, Data); overclaim's agents saw the host's user-level instructions.

## Install and reproduce

```sh
uv sync --group dev
uv run pytest --runslow
uv run evalnoise study      # quick study, about 3 minutes
uv run evalnoise validate   # quick validation, about 7 minutes
uv run python scripts/derived_numbers.py
```
