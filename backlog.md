# Backlog

## In progress

## Waiting on me

- Branch `polish-2026-10-30` (pushed, 3 commits ahead of `main`) merged into `main` after reading the review notes in `docs/release-notes-0.1.0.md`.
- mm-arena's `polish-2026-10-30` merged into its public `main` before evalnoise goes public: 5 of the 17 source files behind `results/trials/mm-arena.csv` exist only on that branch.
- agent-ab, overclaim and ruleproof polish branches merged by merge commit or fast-forward, then `uv run evalnoise extract` committed, so every commit in `results/trials/MANIFEST.json` is public (all four sources now point at unpushed commits; the agent-ab, overclaim and ruleproof data files already match `origin/main`).
- CI green from one manual dispatch (it has never run on GitHub, including the SHA-pinned actions).
- Repository public and v0.1.0 tagged, with `CITATION.cff` `date-released`, the `CHANGELOG.md` entry and the notes in `docs/release-notes-0.1.0.md` matched to the tag date, and a push trigger added to CI with the "private for now" wording removed from `AGENTS.md`.
- Decision on the 42 commits that carry a Claude `Co-Authored-By` trailer: rewrite history before going public, or leave them.

## Decided

- 2026-10-30: no family x run component: it needs a new model term, and with 5 mm-arena families its variance would rest on about 4 df per run pair; the run-shift-by-family table stays the evidence.
- 2026-10-30: the design effect applies only to the tasks-needed tables, so the grid and reference-design MDEs stay comparable with `scripts/derived_numbers.py`; item df stay `T - 1`.
- 2026-10-30: no bootstrap coverage check with partial runs and unequal residuals: the pooled item x run variance then has no single true value to cover; `pairs-*` covers the run interval, which has one.

## Proposed

- REPORT.md updated from the full profiles (`bash scripts/longrun.sh`, resumable; about 3 hours of CPU, most of it `coverage-t60-a3-r3`; `results/*-full/` stays gitignored until then).
- The pass/fail study datasets reported with and without tasks no trial passed, so the tables, not only derived numbers, show both.
- A harness-version term, or more same-version mm-arena runs, separating version shifts from within-version drift (only haiku r3 and r4 share a recorded version).
- BCa or a parametric bootstrap evaluated for `item_arm` with about 40 items, where the percentile interval covers 0.85.
- A rerun of one agent-ab or overclaim arm, so the run variance is estimable there.
- A per-arm (heteroscedastic) residual for pass/fail data.
