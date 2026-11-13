"""REPORT.md and README.md publish copies of generated output, never typed numbers.

REPORT tables are rows of results/published.md (scripts/published_tables.py, from the committed
study and validation results); the README's examples are the CLI's own output. CI reruns the
study, the validation and the script and fails on any diff under results/.
"""

import importlib.util
from pathlib import Path

import pytest

from evalnoise.cli import main

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "results" / "published.md"
TRIALS = str(ROOT / "results" / "trials" / "agent-ab-no-tests.csv")


def _rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("| ")]


def _script():
    path = ROOT / "scripts" / "published_tables.py"
    spec = importlib.util.spec_from_file_location("published_tables", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_tables_render_from_the_committed_results(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert PUBLISHED.read_text(encoding="utf-8") == _script().render()


def test_every_report_table_row_is_a_published_row():
    source = set(_rows(PUBLISHED.read_text(encoding="utf-8")))
    rows = _rows((ROOT / "REPORT.md").read_text(encoding="utf-8"))
    assert len(rows) > 50
    assert [row for row in rows if row not in source] == []


@pytest.mark.parametrize(
    "argv",
    [
        ["components", TRIALS, "--score-col", "passed", "--scale", "100", "--pair",
         "no-tests,control"],
        ["power", TRIALS, "--score-col", "passed", "--scale", "100", "--run-var", "0",
         "--tasks", "20,50,100", "--repeats", "1,3", "--mde", "5,10"],
    ],
)  # fmt: skip
def test_readme_examples_show_the_commands_output(argv, capsys):
    assert main(argv) == 0
    printed = _rows(capsys.readouterr().out)
    assert printed
    readme = set(_rows((ROOT / "README.md").read_text(encoding="utf-8")))
    assert [row for row in printed if row not in readme] == []
