"""Render the results tables REPORT.md publishes, from the committed study and validation results.

Writes results/published.md. Every numeric row of a REPORT.md table must be a row here
(tests/test_published.py); CI reruns `evalnoise study`, `evalnoise validate` and this script
and fails on any diff under results/. Tables are reshaped from the generated summaries
(results/study/summary.md, which `evalnoise study` writes from the committed units) or read
from the unit files where the report rounds differently.

Run from the repository root: uv run python scripts/published_tables.py
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path("results")
OUT = RESULTS / "published.md"
STUDY = RESULTS / "study"
VALIDATION = RESULTS / "validation"

SOURCES = {
    "mm-arena-replicated": ("[mm-arena](https://github.com/h-a-forster/mm-arena) core-v1",
                            "edge captured, pp"),
    "mm-arena-all": ("same, all 9 LLM setups", "edge captured, pp"),
    "agent-ab-no-tests": ("[agent-ab](https://github.com/h-a-forster/agent-ab)", "passed, pp"),
    "agent-ab-no-tests-cost": ("same", "log cost (log USD)"),
    "agent-ab-haiku-vs-sonnet": ("same", "passed, pp"),
    "overclaim-setups": ("[overclaim](https://github.com/h-a-forster/overclaim) study 1",
                         "passed, pp"),
    "overclaim-interventions": ("overclaim study 2", "passed, pp"),
    "ruleproof-main": ("[ruleproof](https://github.com/h-a-forster/ruleproof) bench",
                       "all rules followed, pp"),
    "ruleproof-pressure": ("ruleproof pressure tasks", "all rules followed, pp"),
}  # fmt: skip
PLANNING_SKIP = {"agent-ab-no-tests-cost"}  # its MDE is in log USD; the report quotes it in prose
RUNS_TABLE = ("mm-arena-replicated", ["10 pp", "5 pp"], [1, 2, 3, 4, 5, 6, 8, 10, 15, 20])
REPEATS_TABLE = [
    ("agent-ab-no-tests", "5 pp"),
    ("agent-ab-no-tests", "10 pp"),
    ("overclaim-interventions", "10 pp"),
]
REPEATS_COLUMNS = ["R1 K1", "R1 K3", "R3 K1", "R5 K1"]
PAIRS = [  # (unit, first, second): the report's mm-arena pairs, in its order
    ("mm-arena-replicated", "fable-5-1@high", "opus-5-5@high"),
    ("mm-arena-replicated", "fable-5-1@high", "haiku-5-5@high"),
    ("mm-arena-replicated", "haiku-5-5@high", "opus-5-5@high"),
    ("mm-arena-all", "opus-5-5@high", "opus-5-5@medium"),
    ("mm-arena-all", "sonnet-5-5@high", "sonnet-5-5@low"),
]
PREFIX = "claude-cli:claude-"


def sections(path: Path) -> dict[str, list[list[str]]]:
    """Body rows of every Markdown table in a generated summary, by section title."""
    out: dict[str, list[list[str]]] = {}
    title = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            title = line[3:]
        elif title and line.startswith("| ") and not line.startswith("| ---"):
            out.setdefault(title, []).append(
                [c.strip() for c in line.strip().strip("|").split("|")]
            )
    return {t: rows[1:] for t, rows in out.items()}  # drop each header row


def table(header: list[str], align: str, rows: list[list[str]]) -> list[str]:
    def row(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    return [row(header), "|" + "|".join(align) + "|", *(row(r) for r in rows), ""]


def name(cell: str) -> str:
    return cell.removesuffix(" (few)")


def fmt_p(p: float) -> str:
    """p-values as the report quotes them: two decimals from 0.1, three below, `<0.001`."""
    if p < 0.001:
        return "<0.001"
    return f"{p:.3f}" if p < 0.1 else f"{p:.2f}"


def study_tables(out: list[str]) -> None:
    s = sections(STUDY / "summary.md")
    rows = []
    for ds, arms, items, runs, repeats, trials, _unit in s["Datasets"]:
        key = ds.strip("`")
        source, score = SOURCES[key]
        spread = runs.split("/")
        runs = spread[0] if len(spread) == 1 else f"{spread[0]}-{spread[-1]}"
        rows.append([ds, source, arms, items, runs, repeats, trials, score])
    out += ["## Datasets", ""]
    out += table(
        ["Dataset", "Source", "Arms", "Items", "Runs per arm", "Repeats", "Trials", "Score"],
        ["---", "---", "---:", "---:", "---", "---:", "---:", "---"], rows)  # fmt: skip

    out += ["## Variance components (SD)", ""]
    out += table(
        ["Dataset", "item", "item x arm", "run", "item x run", "within run", "ICC item"],
        ["---"] + ["---:"] * 6, s["Variance components (SD)"])  # fmt: skip

    rows = []
    for ds, design, se_items, se_run, mde, mde_ends, _share, fpr in s[
        "Planning: paired comparison, one run per arm"
    ]:
        if name(ds).strip("`") in PLANNING_SKIP:
            continue
        identified = se_run != "-"
        # The bootstrap interval of the MDE holds the run term fixed, so it is shown only
        # where the run term adds nothing.
        run_matters = identified and se_run != se_items
        rows.append([
            name(ds), design, se_items, se_run if identified else "n/i",
            mde.split(" [")[0] if run_matters else mde,
            mde_ends.strip("[]").replace(", ", " to ") if identified else "-", fpr,
        ])  # fmt: skip
    out += ["## Planning", ""]
    out += table(
        ["Dataset", "Tasks x repeats", "SE, items only", "SE with run term", "MDE",
         "MDE at run CI ends", "Naive false-positive rate"],
        ["---", "---:", "---:", "---:", "---:", "---:", "---:"], rows)  # fmt: skip

    needed = {
        (name(ds).strip("`"), target): dict(c.split(": ") for c in cells.split("; "))
        for ds, target, cells in s["Tasks per arm needed for a target MDE"]
    }
    unit, targets, runs = RUNS_TABLE
    rows = [[t, *(needed[unit, t][f"R{r} K1"] for r in runs)] for t in targets]
    out += ["## Episodes per setup, mm-arena-replicated", ""]
    out += table(["Target", *(f"R{r}" for r in runs)], ["---"] + ["---:"] * len(runs), rows)
    rows = [[f"`{ds}`", t, *(needed[ds, t][c] for c in REPEATS_COLUMNS)] for ds, t in REPEATS_TABLE]
    out += ["## Tasks per arm, pass/fail datasets", ""]
    out += table(["Dataset", "Target", *REPEATS_COLUMNS], ["---"] + ["---:"] * 5, rows)


def pairs_table(out: list[str]) -> None:
    rows = []
    units = {u: json.loads((STUDY / "units" / f"{u}.json").read_text(encoding="utf-8"))
             for u, _, _ in PAIRS}  # fmt: skip
    summary = {
        (name(ds).strip("`"), pair): cells
        for ds, pair, *cells in sections(STUDY / "summary.md")["Pairwise differences"]
    }
    for unit, a, b in PAIRS:
        pair = f"{PREFIX}{a} - {PREFIX}{b}"
        e = units[unit]["pair_estimates"][pair]
        cells = summary[unit, pair]
        without = list(e["p_with_run_without"].values())
        lo, hi = fmt_p(min(without)), fmt_p(max(without))
        rows.append([
            # p_items is the clustered test's p (the summary's "p, clusters").
            f"`{a}` - `{b}`", cells[0], cells[1], cells[2], fmt_p(e["p_items"]), cells[4], cells[5],
            f"{e['df_with_run']:.1f} / {fmt_p(e['p_with_run'])}",
            lo if lo == hi else f"{lo} to {hi}",
        ])  # fmt: skip
    out += ["## Pairwise differences, mm-arena", ""]
    out += table(
        ["Pair (mm-arena)", "Difference, pp [item bootstrap]", "SE, episodes", "SE, games",
         "p, games", "SE, families", "SE with run term", "df / p with run term",
         "p, run variance without one setup"],
        ["---"] + ["---:"] * 8, rows)  # fmt: skip


def validation_table(out: list[str]) -> None:
    def unit(check: str) -> dict:
        return json.loads((VALIDATION / "units" / f"{check}.json").read_text(encoding="utf-8"))

    def r(check: str, q: str, digits: int = 3) -> str:
        return f"{unit(check)['rates'][q]['rate']:.{digits}f}"

    def ci(check: str, q: str) -> str:
        x = unit(check)["rates"][q]
        return f"{x['rate']:.3f} [{x['mc95'][0]:.3f}, {x['mc95'][1]:.3f}]"

    def nominal(check: str, q: str) -> str:
        return f"{unit(check)['rates'][q]['nominal']:.3f}"

    power = ["power-t20-k1", "power-t50-k3", "power-t10-k5"]
    binary = ["binary-t50-k3", "binary-t30-k1"]
    p90 = ["binary-p90-t50-k3-up", "binary-p90-t50-k3-down"]
    cov2 = [r("coverage-t40-a2-k3", q, 2) for q in ("item", "item_arm", "within")]
    cov3 = [r("coverage-t60-a3-r3", q, 2) for q in ("item", "item_arm", "item_run", "run (MLS)")]
    rows = [
        ["paired t over items, 20 x 1 / 50 x 3 / 10 x 5", "size",
         " / ".join(r(c, "null") for c in power), "0.05"],
        ["same", "power at planned MDE", " / ".join(r(c, "at_mde") for c in power), "0.80"],
        ["run-aware t, 60 tasks, 3 runs", "size", ci("runs-t60-r3", "null"), "0.05"],
        ["same", "power at planned MDE", ci("runs-t60-r3", "at_mde"), "0.80"],
        ["run-aware t, 60 tasks, 6 runs", "size / power",
         f"{r('runs-t60-r6', 'null')} / {r('runs-t60-r6', 'at_mde')}", "0.05 / 0.80"],
        ["run-blind paired t, 1 run, 120 / 30 tasks", "false-positive rate",
         f"{r('naive-t120-r1', 'null')} / {r('naive-t30-r1', 'null')}",
         f"{nominal('naive-t120-r1', 'null')} / {nominal('naive-t30-r1', 'null')}"],
        ["pass/fail (logistic), 50 x 3 / 30 x 1, pass rate 60 to 70%", "size",
         " / ".join(r(c, "null") for c in binary), "0.05"],
        ["same", "power at planned MDE", " / ".join(r(c, "at_mde") for c in binary), "0.80"],
        ["pass/fail near 90% pass, 50 x 3, gain / loss", "size",
         " / ".join(r(c, "null") for c in p90), "0.05"],
        ["same", "power at planned MDE, variance at the shifted rate",
         " / ".join(r(c, "at_mde") for c in p90), "0.80"],
        ["same, loss planned from the base-rate variance", "power at planned MDE",
         ci("binary-p90-t50-k3-down-base", "at_mde"), "0.80"],
        ["run variance borrowed from a pilot (7 run df), 120 tasks, 1 run", "size / power",
         f"{r('borrowed-t120-r1', 'null')} / {r('borrowed-t120-r1', 'at_mde')}", "0.05 / 0.80"],
        ["bootstrap, 40 tasks x 2 arms x 3 repeats", "coverage: item / item x arm / within",
         " / ".join(cov2), "0.95"],
        ["bootstrap and MLS, 60 tasks x 3 arms x 3 runs",
         "coverage: item / item x arm / item x run / run", " / ".join(cov3), "0.95"],
        ["mm-arena-like: 120 tasks, setups with 2/2/2/4 runs, one half run, item x run variance "
         "50 to 300", "size of the run-aware pair test / MLS run coverage",
         f"{r('pairs-t120-mm', 'null (run-aware pair test)')} / {r('pairs-t120-mm', 'run (MLS)')}",
         "0.05 / 0.95"],
    ]  # fmt: skip
    out += ["## Validation", ""]
    out += table(["Check", "Quantity", "Rate", "Planner"], ["---", "---", "---:", "---:"], rows)


def render() -> str:
    out = [
        "# Published tables",
        "",
        "Generated by `scripts/published_tables.py` from results/study and results/validation;",
        "REPORT.md copies these rows. Do not edit by hand.",
        "",
    ]
    study_tables(out)
    pairs_table(out)
    validation_table(out)
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> None:
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
