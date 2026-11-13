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
- The repository is public; CI runs on pushes to main, pull requests and manual dispatch.
- Release hygiene: no personal names, local user paths or machine details in committed
  files, outputs or logs. `MANIFEST.json` paths are relative to the repository root.
- REPORT tables are copies of rows in `results/published.md`, and the README's examples are the
  CLI's output; never type a number into a table. `tests/test_published.py` and CI (which reruns
  `study`, `validate` and the script, then diffs `results/`) check them. Numbers REPORT marks
  "derived" come from `scripts/derived_numbers.py` and are not checked automatically.
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
| `scripts/published_tables.py` | `results/published.md`: every REPORT table, reshaped from the summaries and units |

## How to test

```sh
uv sync --group dev
uv run pytest                 # fast suite (CI), offline
uv run pytest --runslow       # plus the quick Monte Carlo validation
uv run ruff check .
uv run ruff format --check .
uv run evalnoise study        # quick study, about 3 minutes
uv run evalnoise validate     # quick validation, about 7 minutes
```

## Status

v0.1.0, public repository. Open work is in `backlog.md` (gitignored, local only).
