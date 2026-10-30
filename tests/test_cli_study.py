import json

import pandas as pd
import pytest

from evalnoise import study
from evalnoise.cli import main
from evalnoise.components import Components
from evalnoise.simulate import simulate


@pytest.fixture
def table(tmp_path):
    df = simulate(Components(4.0, 1.0, 0.5, 0.7, 2.0), tasks=12, arms=2, runs=2, repeats=2, seed=0)
    p = tmp_path / "trials.csv"
    df.to_csv(p, index=False)
    return p


def test_components_cli_json(table, capsys):
    assert (
        main(["components", str(table), "--bootstrap", "20", "--json", "--pair", "arm1,arm0"]) == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["trials"] == len(table.read_text().splitlines()) - 1
    assert set(out["components"]) >= {"item", "item_arm", "run", "item_run", "within"}
    assert "arm1 - arm0" in out["pairs"]


def test_components_cli_text_with_reml(table, capsys):
    assert main(["components", str(table), "--bootstrap", "20", "--reml"]) == 0
    out = capsys.readouterr().out
    assert "item x arm" in out and "REML" in out and "chi-square" in out


def test_power_cli_from_components(capsys):
    args = [
        "power",
        "--components",
        "item=400,item_arm=60,run=20,item_run=100,within=300",
        "--tasks",
        "20,50",
        "--runs",
        "1,4",
        "--repeats",
        "1",
        "--mde",
        "12",
    ]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "unreachable" in out  # one run per arm cannot reach 12
    assert "4 run(s) x 1 repeat(s):" in out


def test_power_cli_requires_run_variance_for_single_run_data(tmp_path, capsys):
    df = simulate(Components(4.0, 1.0, 0.0, 0.0, 2.0), tasks=10, arms=2, repeats=2, seed=0)
    p = tmp_path / "one_run.csv"
    df.to_csv(p, index=False)
    assert main(["power", str(p)]) == 2
    assert "not identified" in capsys.readouterr().err
    assert main(["power", str(p), "--run-var", "0", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["components"]["run"] == 0.0


@pytest.mark.parametrize(
    "argv",
    [
        ["power"],
        ["power", "--components", "item=-1"],
        # Regression: omitted item_run / within were silently taken as 0.
        ["power", "--components", "item_arm=70,run=17", "--tasks", "120"],
        ["components", "missing.csv"],
    ],
)
def test_cli_errors_exit_2(argv, capsys):
    try:
        code = main(argv)
    except SystemExit as exc:  # argparse rejects bad option values itself
        code = exc.code
    assert code == 2


def _study_files(tmp_path, table):
    repo = tmp_path / "repo"
    (repo / "configs").mkdir(parents=True)
    (repo / "results" / "trials").mkdir(parents=True)
    (repo / "results" / "trials" / "sim.csv").write_text(table.read_text(), encoding="utf-8")
    cfg = repo / "configs" / "study.toml"
    cfg.write_text(
        "[profiles.quick]\nbootstrap = 20\nseed = 1\n"
        '[[dataset]]\nid = "sim"\nname = "sim"\ntable = "sim"\nscore = "score"\ntargets = [3]\n',
        encoding="utf-8",
    )
    return repo, cfg


def test_study_resumes_and_invalidates_on_schema_change(tmp_path, table, monkeypatch):
    repo, cfg = _study_files(tmp_path, table)
    out = repo / "results" / "study"
    first = study.run_study(cfg, out)
    assert first[0]["planning"]["run_assumption"] == "estimated"
    assert (out / "units" / "sim.json").is_file()
    # Regression: result files store nan as null, which from_dict could not read back.
    unit = json.loads((out / "units" / "sim.json").read_text(encoding="utf-8"))
    unit["components"]["within"] = None
    back = Components.from_dict(unit["components"])
    assert back.item == unit["components"]["item"] and back.within != back.within
    study.run_study(cfg, out)
    log = (out / "progress.log").read_text(encoding="utf-8")
    assert "up to date, skipped" in log
    # Regression: a code change that alters results must not reuse stale units.
    monkeypatch.setattr(study, "SCHEMA", study.SCHEMA + 1)
    study.run_study(cfg, out)
    assert (out / "progress.log").read_text(encoding="utf-8").count("done in") == 2


def test_study_cli_writes_summary(tmp_path, table, capsys):
    repo, cfg = _study_files(tmp_path, table)
    out = repo / "results" / "study"
    assert main(["study", "--config", str(cfg), "--out", str(out)]) == 0
    text = (out / "summary.md").read_text(encoding="utf-8")
    assert "## Variance components (SD)" in text and "`sim`" in text
    assert main(["study", "--config", str(cfg), "--out", str(out), "--only", "nope"]) == 2


def test_validate_cli_single_check(tmp_path, capsys):
    out = tmp_path / "v"
    assert main(["validate", "--out", str(out), "--only", "naive-t30-r1"]) == 0
    unit = json.loads((out / "units" / "naive-t30-r1.json").read_text(encoding="utf-8"))
    null = unit["rates"]["null"]
    assert null["nominal"] > 0.05
    assert null["mc95"][0] - 0.02 <= null["nominal"] <= null["mc95"][1] + 0.02


def test_validation_shards_resume(tmp_path, monkeypatch):
    from evalnoise import validate

    tiny = dict(validate.PROFILES["quick"], sims=300, shards=3)
    monkeypatch.setitem(validate.PROFILES, "tiny", tiny)
    out = tmp_path / "v"
    first = validate.run_validation(out, "tiny", only=["power-t20-k1"])
    assert first[0]["sims"] == 300
    (out / "units" / "power-t20-k1" / "shard-1.json").unlink()
    again = validate.run_validation(out, "tiny", only=["power-t20-k1"])
    log = (out / "progress.log").read_text(encoding="utf-8")
    assert log.count("shard 2/3 done") == 2 and log.count("shard 1/3 done") == 1
    assert again[0]["rates"] == first[0]["rates"]  # shard seeds are fixed


DATASET = {"id": "x", "name": "x", "table": "x", "score": "score", "targets": []}
PROFILE = {"bootstrap": 20, "seed": 0}


def test_analyse_reports_per_arm_run_terms_and_unequal_residuals():

    a = simulate(Components(4.0, 1.0, 0.5, 0.2, 0.0), tasks=60, arms=1, runs=3, seed=1)
    b = simulate(Components(4.0, 1.0, 0.5, 3.0, 0.0), tasks=60, arms=1, runs=3, seed=2)
    df = pd.concat([a, b.assign(arm="arm1")], ignore_index=True)
    res = study.analyse(df, DATASET, PROFILE, {})
    by_arm = res["run_by_arm"]
    assert by_arm["residual_homogeneity"]["p"] < 0.001
    assert any("do not share one item x run variance" in n for n in res["planning"]["notes"])
    # With two arms, leaving one out leaves the other arm's own estimate.
    assert by_arm["leave_one_out"]["arm0"]["run"] == pytest.approx(by_arm["arms"]["arm1"]["run"])
    p = res["pair_estimates"]["arm0 - arm1"]
    # The run term has 4 df: the test with it has far fewer df than the 59 of the items.
    assert 1 < p["df_with_run"] < 59 and p["p_with_run"] > p["p_items"]


def test_analyse_flags_pairs_that_differ_on_few_items():

    items = [f"t{j}" for j in range(30)]
    base = pd.DataFrame({"item": items, "run": "r0", "repeat": 0, "cluster": items})
    s0 = [1.0] * 25 + [0.0] * 5
    s1 = list(s0)
    s1[0] = s1[1] = 0.0
    s1[29] = 1.0
    df = pd.concat(
        [base.assign(arm="a", score=s0), base.assign(arm="b", score=s1)], ignore_index=True
    )
    res = study.analyse(df, DATASET, PROFILE, {})
    assert res["pair_estimates"]["a - b"]["items_differing"] == 3
    assert res["planning"]["few_items_differing"] == {"a - b": 3}


def test_binary_check_direction(tmp_path, monkeypatch):
    from evalnoise import validate

    tiny = dict(validate.PROFILES["quick"], binary_sims=10)
    monkeypatch.setitem(validate.PROFILES, "tiny", tiny)
    up, down = validate.run_validation(
        tmp_path, "tiny", only=["binary-p90-t50-k3-up", "binary-p90-t50-k3-down"]
    )
    assert abs(up["context"]["base_pass"] - 0.9) < 0.01
    assert up["context"]["logit_shift"] > 0 > down["context"]["logit_shift"]
