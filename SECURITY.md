# Security policy

Security fixes are made for the latest release.

## Reporting

Report vulnerabilities privately through the repository's **Security** tab ("Report a
vulnerability"). Do not open a public issue. Include the evalnoise version, the operating
system, the impact, and steps that reproduce it.

## Scope

evalnoise reads local result files (CSV, JSON Lines, Inspect JSON logs, lm-eval sample
files, and the result directories listed in `configs/sources.toml`) and writes CSV, JSON and
Markdown under the output directories you pass. It makes no network requests and calls no
models. `evalnoise extract` runs `git rev-parse` and `git ls-files` in the source
repositories to record provenance.

In scope:

- evalnoise reading, writing or deleting files outside the paths given on the command line
  or in its config files (for example through table names, dataset ids or values inside
  result files);
- local absolute paths or other machine details written to committed outputs
  (`results/trials/MANIFEST.json`, study and validation units);
- code execution triggered by the contents of a result file.

Out of scope:

- vulnerabilities in dependencies (report those upstream);
- statistical disagreements (open an ordinary issue; see CONTRIBUTING.md).
