# Contributing

Bug reports, new input adapters, new datasets and documentation fixes are welcome. Read
[docs/DESIGN.md](docs/DESIGN.md) first: it fixes the model, the estimands, what each data
layout identifies and how results are validated.

## Setup

You need [uv](https://docs.astral.sh/uv/) and git. From a clone:

```sh
uv sync --group dev
uv run evalnoise --version
```

## Tests and lint

```sh
uv run pytest              # fast suite, offline
uv run pytest --runslow    # plus the quick Monte Carlo validation (about 7 minutes)
uv run ruff check .
uv run ruff format --check .
```

CI runs lint and the fast suite on Ubuntu (Python 3.11, locked and lowest declared
dependencies) and Windows (Python 3.13). Tests
must run offline, write only under pytest's `tmp_path`, use fixed seeds and pass on
Windows. Statistical assertions state their tolerance in Monte Carlo standard errors. Mark
tests that take more than a few seconds `@pytest.mark.slow`. A bug fix comes with a test
that fails without it.

## Code

- Python 3.11+, typed. Runtime dependencies: numpy, scipy, pandas. Open an issue before
  adding one. statsmodels is a test-only reference.
- Validate inputs before writing anything and fail with a clear `DataError` rather than
  silently dropping data. Count every excluded trial.
- Long computations are units written atomically and skipped on rerun (`evalnoise study`,
  `evalnoise validate`). Bump `SCHEMA` in `study.py` or `validate.py` when a change alters
  their results, so cached units are recomputed.
- Line length 100; ruff enforces the rest. Write text files as UTF-8.

## Data

- `results/trials/` holds small derived per-trial tables with provenance in
  `MANIFEST.json`; regenerate them with `uv run evalnoise extract`, never by hand.
- Never commit raw downloads, caches or scratch output (`data/`, `runs/`, `tmp/`).
- A new dataset needs its source's licence to allow redistribution of per-trial scores.

## Pull requests

- One change per pull request, with tests and docs.
- Describe user-visible changes in `docs/release-notes-<version>.md`, not in the changelog.

Security issues: see [SECURITY.md](SECURITY.md).
