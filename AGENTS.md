# AGENTS.md

Guide for coding agents (and humans) working on evalnoise. Read `docs/DESIGN.md` before
changing any statistics or data handling: it holds the model, estimands, identification
table, estimators, interval methods and validation plan this file points to.

## What this is

A Python package, CLI and small study. It estimates variance components of agent-eval
scores (item, item x arm, run, item x run, within run) from per-trial results, with
intervals, and plans how many tasks, repeats and runs a comparison needs. The study applies
it to per-trial data published by four Claude-only agent-eval projects (mm-arena, agent-ab,
overclaim, ruleproof).

## Conventions

- uv + hatchling, `src/` layout, Python >= 3.11 (local dev 3.13 via `.python-version`),
  typed code, `ruff check` + `ruff format` (line length 100), pytest. `[tool.uv]
  exclude-newer` keeps the lock on releases at least two weeks old; move it deliberately.
- Runtime dependencies: numpy, scipy, pandas only. statsmodels is a dev-only reference for
  the REML tests.
- Trial table columns: `item, arm, run, repeat, cluster, score`. Run labels are scoped to
  their arm. `Components` fields are variances; `nan` = not identified; `absorbed` says
  where an unidentified part was folded.
- Every stochastic function takes a seed; study and validation units derive seeds from
  `(profile seed, crc32(unit id))` (and the shard index for validation).
- No model or network calls. CPU only.
- Long jobs: `evalnoise study` and `evalnoise validate` write one file per finished unit
  (validation: per shard) atomically, skip finished units on rerun and append to
  `progress.log`. Bump `SCHEMA` in `study.py` / `validate.py` when results would change.
  Commands here should stay under about 8 minutes; longer runs (the `full` profiles) go
  through `scripts/longrun.sh` (resumable, retries each stage; log in `tmp/longrun.log`).
- Planning must never understate the MDE: unidentified components are folded where they
  do not shrink, and an unidentified run variance must be supplied or explicitly set to 0.
- Validate inputs before writing; raise `DataError` with a clear message; count every
  excluded trial in the manifest.
- Scratch files go in `tmp/` (gitignored). Do not create `.bak` copies; use git.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The repository
  is private for now; CI runs only on pull requests and manual dispatch (metered minutes).
- Release hygiene: no personal names, local user paths or machine details in committed
  files, outputs or logs. `MANIFEST.json` paths are relative to the repository root.
- Statistical honesty: report sizes, seeds and intervals; say when a component is not
  identified or a number is a lower bound; these are a handful of Claude-only datasets, so
  do not generalise beyond them.

## Architecture map

| Path | Role |
|---|---|
| `src/evalnoise/data.py` | read CSV/JSONL, map columns, validate trial tables |
| `src/evalnoise/components.py` | moment estimators (Henderson III runs, two-way ANOVA items), pairs, cluster bootstrap, run MLS interval |
| `src/evalnoise/reml.py` | dense REML cross-check |
| `src/evalnoise/power.py` | variance of a difference (design effect, pass-rate scaling), MDE, tasks needed, naive FPR, optimal repeats |
| `src/evalnoise/simulate.py` | synthetic tables from the model (Gaussian or logistic) |
| `src/evalnoise/adapters.py` | Inspect JSON logs, lm-eval sample files |
| `src/evalnoise/sources.py`, `extract.py` | per-trial tables from the four source layouts, manifest |
| `src/evalnoise/study.py`, `report.py` | the study (units, planning tables) and Markdown rendering |
| `src/evalnoise/validate.py` | Monte Carlo checks of power, false-positive rates and coverage |
| `src/evalnoise/cli.py` | `components / power / extract / study / validate` |
| `configs/sources.toml`, `configs/study.toml` | source tables; study datasets, pairs, targets, profiles |
| `results/trials/` | committed per-trial tables + `MANIFEST.json` |
| `results/study/`, `results/validation/` | committed quick-profile outputs (`summary.md`, units) |

## How to test

```sh
uv sync --group dev
uv run pytest                 # fast suite (CI), offline
uv run pytest --runslow       # plus the quick Monte Carlo validation
uv run ruff check .
uv run ruff format --check .
uv run evalnoise study        # quick study, about 4 minutes
uv run evalnoise validate     # quick validation, about 3 minutes
```

## Status and next steps

Updated: 2026-10-30 (v0.1.0, private repository).

Done:

- Package, CLI, tests (unbiasedness per layout, variance formula vs simulation, REML vs
  statsmodels, realised power, naive false-positive rate, extractors, adapters, resume).
- Quick study over 9 datasets (`results/study/summary.md`) and quick validation
  (`results/validation/summary.md`); write-up in `REPORT.md`.

Next:

1. mm-arena: all replicate runs through haiku r4 (2026-10-30) are in the tables and the
   quick study. Only haiku r3/r4 share a recorded harness version; the model has no
   harness factor (subset refit in `scripts/derived_numbers.py`). More same-version runs,
   or a harness term in the model, would separate version from within-version drift. New
   runs: `uv run evalnoise extract --only mm-arena && uv run evalnoise study`.
2. Run the full profiles (`evalnoise study --profile full --out results/study-full`,
   `evalnoise validate --profile full --out results/validation-full`), about 1 to 1.5
   hours of CPU in total, with `bash scripts/longrun.sh`; then update REPORT.md from their
   summaries (`results/*-full/` is gitignored until then).
3. The percentile bootstrap undercovers `item_arm` with about 40 items (quick validation);
   evaluate BCa or a parametric bootstrap.
4. Datasets with repeats but one run per arm cannot identify the run variance. A rerun of
   one agent-ab or overclaim arm would make it estimable there.
5. Consider a per-arm (heteroscedastic) residual for pass/fail data.

Audit items 6 to 11 (2026-10-30): done, except as noted.

- Done: design effect in `resolve` / `tasks_needed` / `power --design-effect`, applied by
  the study to its tasks-needed tables (median game design effect over pairs); pass/fail
  MDEs with the shifted arm's variance at its own rate where larger, the larger of gain
  and loss (`pass_rate`, `power --pass-rate`; the study detects 0/100 scores via
  `bounds`); Burdick-Graybill (MLS) run-variance interval, capped at `(range / 2)^2` for
  bounded scores; an item-level Brown-Forsythe test next to Bartlett's (it drives the
  planning note); the `pairs-t120-mm` validation check (size of the run-aware pair test
  and MLS coverage with a partial run and sixfold unequal residuals); the slow test
  allows 3 Monte Carlo SEs and names the known gaps (`KNOWN` in
  `tests/test_validation_slow.py`).
- Not done: a family x run component. It needs a new model term and estimator, and with
  5 mm-arena families its variance would rest on about 4 df per run pair, too few to
  plan with; the run-shift-by-family table stays the evidence.
- Not done: the design effect in the grid and reference-design MDEs (only the
  tasks-needed tables use it), so those stay comparable with `derived_numbers.py`, which
  scales the reference SE by the design effect separately. The item df stay `T - 1`.
- Not done: bootstrap coverage with partial runs and unequal residuals. With unequal
  residuals the pooled item x run variance is a df-weighted average with no single true
  value to cover; the `pairs-*` check covers the run interval, which has one.
