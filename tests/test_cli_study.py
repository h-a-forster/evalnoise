import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from evalnoise import study
from evalnoise.cli import main
from evalnoise.components import Components
from evalnoise.data import DataError
from evalnoise.report import study_markdown
from evalnoise.simulate import simulate
from evalnoise.validate import run_validation


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
    capsys.readouterr()
    assert main(["components", str(table), "--bootstrap", "20", "--reml", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out["reml"]) >= {"item", "item_arm", "run", "item_run", "within"}
    lo, hi = out["run_interval"]
    assert out["bootstrap"]["draws"] == 20 and lo <= hi


def test_power_cli_borrows_the_run_df_of_replicate_runs(table, capsys):
    from evalnoise.components import estimate
    from evalnoise.data import load_trials

    assert main(["power", str(table), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["run_df"] == estimate(load_trials(table)).run_term.df > 0


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
    # A design effect and a pass rate near the ceiling both raise the MDE.
    assert main(args[:-2] + ["--json"]) == 0
    base = json.loads(capsys.readouterr().out)["grid"]
    adj = ["--design-effect", "1.5", "--pass-rate", "0.9", "--pass-score", "100", "--json"]
    assert main(args[:-2] + adj) == 0
    out = json.loads(capsys.readouterr().out)
    assert all(a["mde"] > b["mde"] for a, b in zip(out["grid"], base, strict=True))
    assert out["components"]["design_effect"] == 1.5


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
        ["power", "--components", "item_arm=1,run=0,item_run=0,within=1", "--design-effect", "0.5"],
        ["power", "--components", "item_arm=1,run=0,item_run=0,within=1", "--pass-rate", "1"],
        # Regression: without --pass-rate, --pass-score was silently ignored.
        ["power", "--components", "item_arm=1,run=0,item_run=0,within=1", "--pass-score", "100"],
        # Regression: pp variances with the default pass score gave the base-rate MDE silently.
        ["power", "--components", "item_arm=9,run=0,item_run=0,within=500", "--pass-rate", "0.9"],
        ["components", "missing.csv"],
    ],
)
def test_cli_errors_exit_2(argv, capsys):
    try:
        code = main(argv)
    except SystemExit as exc:  # argparse rejects bad option values itself
        code = exc.code
    assert code == 2


def test_power_cli_task_cost_per_run_count(capsys):
    # Regression: --task-cost ignored --runs and always answered for one run.
    comps = "item=400,item_arm=60,run=20,item_run=100,within=300"
    argv = ["power", "--components", comps, "--runs", "1,2", "--task-cost", "20", "--json"]
    assert main(argv) == 0
    k = {x["runs"]: x["repeats"] for x in json.loads(capsys.readouterr().out)["optimal_repeats"]}
    assert k[1] == pytest.approx((300 * 20 / 160) ** 0.5)
    assert k[2] == pytest.approx((150 * 20 / (110 * 2)) ** 0.5)


def test_cli_refuses_merging_runs_from_files_without_run_column(tmp_path, capsys):
    df = simulate(Components(4.0, 1.0, 0.0, 0.0, 2.0), tasks=10, arms=2, repeats=2, seed=0)
    paths = []
    for n in (1, 2):
        p = tmp_path / f"run{n}.csv"
        df.drop(columns="run").to_csv(p, index=False)
        paths.append(str(p))
    assert main(["components", *paths, "--bootstrap", "0"]) == 2
    # Different arms per file are fine: run labels are scoped to their arm.
    df[df["arm"] == "arm0"].drop(columns="run").to_csv(paths[0], index=False)
    df[df["arm"] == "arm1"].drop(columns="run").to_csv(paths[1], index=False)
    assert main(["components", *paths, "--bootstrap", "0", "--json"]) == 0


def test_cli_validates_the_table_merged_from_several_files(tmp_path):
    df = simulate(Components(4.0, 1.0, 0.0, 0.0, 2.0), tasks=10, arms=2, repeats=2, seed=0)
    paths = [tmp_path / "a.csv", tmp_path / "b.csv"]
    # Regression: the same trials in two files counted as repeats, with zero noise between.
    df.to_csv(paths[0], index=False)
    df.to_csv(paths[1], index=False)
    assert main(["components", *map(str, paths), "--bootstrap", "0"]) == 2
    # Regression: an item in a different cluster in each file reached the estimators.
    df[df["arm"] == "arm0"].to_csv(paths[0], index=False)
    df[df["arm"] == "arm1"].assign(cluster="other").to_csv(paths[1], index=False)
    assert main(["components", *map(str, paths), "--bootstrap", "0"]) == 2


def test_cli_routes_eval_logs_to_the_inspect_reader(tmp_path, capsys):
    p = tmp_path / "log.eval"
    p.write_bytes(b"\x28\xb5\x2f\xfd")
    assert main(["components", str(p)]) == 2
    assert "inspect log convert" in capsys.readouterr().err


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


def test_study_refuses_ids_that_escape_the_output_dir(tmp_path, table):
    repo, cfg = _study_files(tmp_path, table)
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('id = "sim"', 'id = "../x"'))
    with pytest.raises(DataError, match="alphanumeric"):
        study.run_study(cfg, repo / "results" / "study")
    assert not (repo / "results" / "study" / "x.json").exists()
    # Regression: an empty table name passed the character check (an empty id is
    # already refused as missing).
    cfg.write_text(
        cfg.read_text(encoding="utf-8")
        .replace("../x", "sim")
        .replace('table = "sim"', 'table = ""')
    )
    with pytest.raises(DataError, match="alphanumeric"):
        study.run_study(cfg, repo / "results" / "study")


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
    pl = res["planning"]
    lo, hi = pl["reference_mde_bootstrap_ci"]
    assert lo < pl["reference_mde"] < hi
    se_i, run = pl["reference_se_items_only"], res["components"]["run"]
    assert pl["reference_se"] ** 2 == pytest.approx(se_i**2 + 2 * run)  # one run per arm
    by_arm = res["run_by_arm"]
    assert by_arm["residual_homogeneity"]["p"] < 0.001
    assert any("do not share one item x run variance" in n for n in res["planning"]["notes"])
    # With two arms, leaving one out leaves the other arm's own estimate.
    assert by_arm["leave_one_out"]["arm0"]["run"] == pytest.approx(by_arm["arms"]["arm1"]["run"])
    p = res["pair_estimates"]["arm0 - arm1"]
    # The run term has 4 df: the test with it has far fewer df than the 59 of the items.
    assert 1 < p["df_with_run"] < 59 and p["p_with_run"] > p["p_items"]
    # Sensitivity: the same test with the run variance of each arm left out in turn.
    assert set(p["p_with_run_without"]) == {"arm0", "arm1"}
    assert all(0 < x <= 1 for x in p["p_with_run_without"].values())


def test_bartlett_matches_scipy():
    rng = np.random.default_rng(0)
    groups = [rng.normal(0, s, n) for s, n in ((1.0, 12), (2.0, 30), (1.5, 8))]
    got = study._bartlett([(float(np.var(g, ddof=1)), len(g) - 1) for g in groups])
    ref = stats.bartlett(*groups)
    assert got["statistic"] == pytest.approx(ref.statistic)
    assert got["p"] == pytest.approx(ref.pvalue)


def test_brown_forsythe_holds_its_size_with_heavy_tails_and_two_run_arms():
    # Equal t(3) residuals in an mm-arena-like layout (runs 2, 2, 4): Bartlett rejects far
    # too often; the item-level Brown-Forsythe test should not (a cell-level one would:
    # with two runs an item's residuals are equal and opposite).
    from evalnoise.components import estimate

    rng = np.random.default_rng(5)
    n_items, sims, rej_bf, rej_bart = 80, 200, 0, 0
    for _ in range(sims):
        parts = []
        for arm, runs in (("a", 2), ("b", 2), ("c", 4)):
            item = np.repeat(np.arange(n_items), runs)
            run = np.tile(np.arange(runs), n_items)
            y = rng.normal(0, 3, n_items)[item] + rng.normal(0, 1, runs)[run]
            y = y + rng.standard_t(3, len(item))
            parts.append(pd.DataFrame({"item": item, "arm": arm, "run": run, "score": y}))
        df = pd.concat(parts, ignore_index=True)
        df = df.assign(item="t" + df["item"].astype(str), run="r" + df["run"].astype(str))
        df = df.assign(repeat=0, cluster=df["item"])
        terms = list(estimate(df).run_terms.values())
        for t in terms:
            assert float(t.residuals @ t.residuals) == pytest.approx(t.rss)
        rej_bf += study._brown_forsythe(terms)["p"] < 0.05
        rej_bart += study._bartlett([(t.rss / t.df_res, t.df_res) for t in terms])["p"] < 0.05
    assert rej_bf / sims < 0.05 + 3 * math.sqrt(0.05 * 0.95 / sims)
    assert rej_bart / sims > 0.3


def test_run_interval_is_capped_by_the_score_bounds():
    # Pass/fail in pp, four tasks, two runs that disagree a lot: the upper end of the run
    # variance interval exceeds what a 0-100 score allows, 50^2.
    items = [f"t{j}" for j in range(4)]
    base = pd.DataFrame({"item": items, "repeat": 0, "cluster": items})
    df = pd.concat(
        [
            base.assign(arm="a", run="r0", score=[0.0, 0.0, 100.0, 0.0]),
            base.assign(arm="a", run="r1", score=[100.0, 100.0, 100.0, 0.0]),
            base.assign(arm="b", run="r0", score=[0.0, 100.0, 100.0, 0.0]),
        ],
        ignore_index=True,
    )
    assert study.analyse(df, DATASET, PROFILE, {})["run_interval"][1] > 2500
    res = study.analyse(df, dict(DATASET, bounds=[0, 100]), PROFILE, {})
    assert res["run_interval"][1] == 2500
    assert res["run_by_arm"]["arms"]["a"]["run_interval"][1] == 2500
    with pytest.raises(DataError, match="outside bounds"):
        study.analyse(df, dict(DATASET, bounds=[0, 1]), PROFILE, {})


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
    planning = study_markdown([res], "quick").split("## Planning: paired", 1)[1]
    assert "`x` (few)" in planning.split("## Planning notes")[0]


def test_binary_check_direction(tmp_path, monkeypatch):
    from evalnoise import validate

    tiny = dict(validate.PROFILES["quick"], binary_sims=10)
    monkeypatch.setitem(validate.PROFILES, "tiny", tiny)
    up, down = validate.run_validation(
        tmp_path, "tiny", only=["binary-p90-t50-k3-up", "binary-p90-t50-k3-down"]
    )
    assert abs(up["context"]["base_pass"] - 0.9) < 0.01
    assert up["context"]["logit_shift"] > 0 > down["context"]["logit_shift"]
    # Regression: nan in the pilot's components made the unit files invalid JSON.
    for r in (up, down):
        text = (tmp_path / "units" / f"{r['name']}.json").read_text()
        json.loads(text, parse_constant=pytest.fail)


@pytest.mark.parametrize("sparse", ["repeats", "replicate runs"])
def test_analyse_survives_draws_without_the_sparse_replicates(sparse):
    # Regression: a bootstrap draw missing the few repeated or replicated items has no
    # within or item x run estimate; the study's MDE interval stopped with a ValueError.
    df = simulate(Components(4.0, 1.0, 0.5, 0.7, 2.0), tasks=8, arms=2, seed=0)
    copied = df[(df["arm"] == "arm0") & df["item"].isin(["t0", "t1"])]
    extra = copied.assign(score=copied["score"] + 1.0)
    extra = extra.assign(repeat=1) if sparse == "repeats" else extra.assign(run="r9")
    res = study.analyse(pd.concat([df, extra], ignore_index=True), DATASET, PROFILE, {})
    lo, hi = res["planning"]["reference_mde_bootstrap_ci"]
    assert 0 < lo <= hi


def test_pair_run_term_counts_partial_runs_as_whole_runs():
    # Run-adjusted item means average every run's shock equally, so a partial replicate run
    # adds a whole run: var(diff) = run * (1/2 + 1), not run / R_eff with R_eff = 1.1.
    from evalnoise.components import estimate

    rng = np.random.default_rng(3)
    items = np.array([f"t{j}" for j in range(40)])
    pairs = [("a", "b")]
    diffs, se2 = [], []
    for _ in range(1000):
        u = rng.normal(0, 3, 40)
        w = rng.normal(0, 1, 3)
        parts = [
            pd.DataFrame({"item": items, "arm": "a", "run": "r1", "y": u + w[0]}),
            pd.DataFrame({"item": items[:4], "arm": "a", "run": "r2", "y": u[:4] + w[1]}),
            pd.DataFrame({"item": items, "arm": "b", "run": "r1", "y": u + w[2]}),
        ]
        df = pd.concat(parts, ignore_index=True)
        df = df.assign(score=df["y"] + rng.normal(0, 0.1, len(df)), repeat=0, cluster=df["item"])
        est = estimate(df, pairs=pairs)
        p = study._pairs_with_run_term(est.pairs, pairs, df, Components(run=1.0), 4.0)["a - b"]
        diffs.append(p["difference"])
        se2.append(p["se_with_run"] ** 2)
    assert np.var(diffs) / np.mean(se2) == pytest.approx(1.0, abs=0.1)


def test_family_clustered_pairs_and_run_shifts_by_family(tmp_path):
    # Run 2 of arm a shifts one of four families only: a family x run effect, which the
    # run term (a shift shared by every item) cannot describe.
    items = [f"f{f}-{j}" for f in range(4) for j in range(10)]
    family = [i.split("-")[0] for i in items]
    rng = np.random.default_rng(0)
    u = rng.normal(0, 3, len(items))
    shift = np.where(np.array(family) == "f0", 8.0, 0.0)
    # Arm b differs from arm a by a family-level offset, which items of a family share.
    offset = np.repeat([3.0, -3.0, 1.0, -1.0], 10) + rng.normal(0, 0.5, len(items))
    base = pd.DataFrame({"item": items, "family": family, "repeat": 0})
    df = pd.concat(
        [
            base.assign(arm="a", run="r1", score=u),
            base.assign(arm="a", run="r2", score=u + shift),
            base.assign(arm="b", run="r1", score=u + shift * 0.5 + offset),
        ],
        ignore_index=True,
    )
    p = tmp_path / "t.csv"
    df.to_csv(p, index=False)
    trials = study._with_families(study.load_trials(p), p, "family")
    res = study.analyse(trials, DATASET, PROFILE, {})
    (s,) = res["run_by_arm"]["shifts"]
    assert s["by_family"] == pytest.approx({"f0": 8.0, "f1": 0.0, "f2": 0.0, "f3": 0.0})
    assert s["mean"] == pytest.approx(2.0) and s["median"] == pytest.approx(0.0)
    pe = res["pair_estimates"]["a - b"]
    assert pe["families"] == 4 and pe["se_families"] > pe["se_clusters"]
    bad = df.assign(family=np.where(df["arm"] == "b", "other", df["family"]))
    bad.to_csv(p, index=False)
    with pytest.raises(study.DataError, match="more than one family"):
        study._with_families(study.load_trials(p), p, "family")


def test_component_cell_marks_negative_estimates():
    from evalnoise.report import component_cell

    def unit(v, lo, hi):
        comps = {"item_arm": v, "absorbed": {}}
        return {"components": comps, "bootstrap": {"components": {"item_arm": [lo, hi]}}}

    assert component_cell(unit(-4.0, -9.0, -1.0), "item_arm") == "<0 [upper bound < 0]"
    assert component_cell(unit(-4.0, -9.0, 4.0), "item_arm").startswith("<0 [")
    assert component_cell(unit(4.0, 1.0, 9.0), "item_arm") == "2.0 [1.0, 3.0]"


def test_validation_rerun_from_finished_shards_leaves_the_pooled_unit_untouched(tmp_path):
    name = "naive-t30-r1"
    committed = Path(__file__).resolve().parents[1] / "results" / "validation" / "units"
    units = tmp_path / "units"
    shutil.copytree(committed / name, units / name)
    unit = json.loads((committed / f"{name}.json").read_text(encoding="utf-8"))
    # Written on another platform: scipy's interval can differ in the last bit.
    mc95 = unit["rates"]["null"]["mc95"]
    mc95[0] = float(np.nextafter(mc95[0], 1.0))
    path = units / f"{name}.json"
    path.write_text(json.dumps(unit, indent=1) + "\n", encoding="utf-8", newline="\n")
    before = path.read_bytes()
    run_validation(tmp_path, "quick", only=[name])
    assert path.read_bytes() == before
    unit["rates"]["null"]["rate"] += 0.001  # a unit whose counts its shards do not give
    path.write_text(json.dumps(unit, indent=1) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(RuntimeError, match="does not match its own shards"):
        run_validation(tmp_path, "quick", only=[name])
