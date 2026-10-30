# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
