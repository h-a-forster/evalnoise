import json

import pytest

from evalnoise.data import DataError
from evalnoise.extract import run_extract
from evalnoise.sources import agent_ab, mm_arena, ruleproof


def _trace(agent, gid, seed, xpnl, status="ok", prior_std=2.0):
    return {
        "agent": agent,
        "game": {"id": gid, "family": "dice", "variant": "classic", "prior_std": prior_std},
        "seed": seed,
        "status": status,
        "xpnl": xpnl,
    }


def _write(path, rows, tail=""):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail, encoding="utf-8")


@pytest.fixture
def arena(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    eps = [("g1", 0), ("g1", 1), ("g2", 0)]
    _write(a / "bayes.jsonl", [_trace("bayes", g, s, 2.0) for g, s in eps])
    _write(a / "claude-cli_m@high.jsonl", [_trace("claude-cli:m@high", g, s, 1.0) for g, s in eps])
    _write(a / "random.jsonl", [_trace("random", g, s, -5.0) for g, s in eps])
    return tmp_path, a


def test_mm_arena_scores_and_replicates(arena):
    root, a = arena
    b = root / "b"
    b.mkdir()
    # Second root: a copy of r1 plus a partial replicate with a truncated last line.
    (b / "claude-cli_m@high.jsonl").write_text(
        (a / "claude-cli_m@high.jsonl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write(
        b / "claude-cli_m@high_r2.jsonl",
        [
            _trace("claude-cli:m@high#r2", "g1", 0, 2.0),
            _trace("claude-cli:m@high#r2", "g1", 1, 0, "error"),
        ],
        tail='{"agent": "claude-cli:m@high#r2", "ga',
    )
    ex = mm_arena([a, b])
    t = ex.table
    assert set(t["arm"]) == {"claude-cli:m@high"}  # baselines other than the reference skipped
    assert sorted(t["run"].unique()) == ["r1", "r2"]
    r1 = t[t["run"] == "r1"]
    assert r1["edge_pp"].tolist() == pytest.approx([50.0, 50.0, 50.0])
    assert t.loc[t["run"] == "r2", "edge_pp"].tolist() == pytest.approx([100.0])
    assert set(t["cluster"]) == {"g1", "g2"}
    assert ex.excluded == {
        "duplicate copy (identical)": 3,
        "status error": 1,
        "truncated last line": 1,
    }


def test_mm_arena_conflicting_copy_fails(arena):
    root, a = arena
    b = root / "b"
    b.mkdir()
    _write(b / "claude-cli_m@high.jsonl", [_trace("claude-cli:m@high", "g1", 0, 1.5)])
    with pytest.raises(DataError, match="conflicting"):
        mm_arena([a, b])


def test_mm_arena_corrupt_middle_line_fails(arena):
    _, a = arena
    (a / "claude-cli_m@high.jsonl").write_text('{"x": 1\n{"y": 2}\n', encoding="utf-8")
    with pytest.raises(DataError, match="invalid JSON"):
        mm_arena([a])


def test_agent_ab(tmp_path):
    rows = [
        {
            "task": "t1",
            "arm": "a",
            "repeat": 0,
            "status": "pass",
            "cost_usd": 0.1,
            "agent_version": "1",
        },
        {"task": "t1", "arm": "b", "repeat": 0, "status": "fail", "cost_usd": 0.2},
        {"task": "t2", "arm": "a", "repeat": 0, "status": "error", "cost_usd": None},
    ]
    d = tmp_path / "exp"
    d.mkdir()
    _write(d / "trials.jsonl", rows)
    ex = agent_ab(d)
    assert ex.table["passed"].tolist() == [1.0, 0.0]
    assert ex.table["run"].unique().tolist() == ["exp"]
    assert ex.excluded == {"status error": 1}
    _write(d / "trials.jsonl", rows[:1] * 2)
    with pytest.raises(DataError, match="duplicate"):
        agent_ab(d)


def _rp(results, run_dir, run_id, arm, task, rep, failed=0, hidden=True):
    p = results / run_dir / "trials" / arm / task / f"r{rep}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "trial": {
            "run_id": run_id,
            "arm": arm,
            "task": task,
            "rep": rep,
            "hidden_pass": hidden,
            "agent_version": "2.1",
            "error": None,
            "model": "m",
        },
        "report": {"summary": {"failed": failed, "unverified": 0}},
    }
    p.write_text(json.dumps(rec), encoding="utf-8")


def test_ruleproof_dedupes_copies_and_renames(tmp_path):
    res = tmp_path / "results"
    _rp(res, "p2", "p2", "y", "t1", 1, failed=1)
    _rp(res, "p3", "p2", "y", "t1", 1, failed=1)  # identical copy in another run's directory
    _rp(res, "p3", "p3", "x", "t1", 1)
    _rp(res, "base", "base", "old", "t1", 1)
    ex = ruleproof(res, runs=["p2", "p3", "base"], rename={"base:old": "new"})
    t = ex.table.sort_values(["run", "arm"])
    assert t["run"].tolist() == ["base", "p2", "p3"]
    assert t["arm"].tolist() == ["new", "y", "x"]
    assert t["all_rules"].tolist() == [1.0, 0.0, 1.0]
    assert ex.excluded == {"copy outside its run directory": 1}


def test_ruleproof_disagreeing_copies_fail(tmp_path):
    res = tmp_path / "results"
    _rp(res, "p2", "p2", "y", "t1", 1, failed=1)
    _rp(res, "p3", "p2", "y", "t1", 1, failed=0)
    with pytest.raises(DataError, match="disagree"):
        ruleproof(res, runs=["p2"])


def test_extract_validates_before_writing(tmp_path, arena):
    root, a = arena
    repo = root / "repo"
    (repo / "configs").mkdir(parents=True)
    cfg = repo / "configs" / "sources.toml"
    cfg.write_text(
        '[[table]]\nname = "arena"\nextractor = "mm-arena"\nrepo = "x"\npaths = ["../a"]\n'
        '[[table]]\nname = "missing"\nextractor = "agent-ab"\nrepo = "x"\npaths = ["../nope"]\n',
        encoding="utf-8",
    )
    out = repo / "results"
    with pytest.raises(DataError, match="not found"):
        run_extract(cfg, out)
    assert not out.exists()
    m = run_extract(cfg, out, only=["arena"])
    assert m["arena"]["rows"] == 3
    assert "../a" in m["arena"]["source_paths"]
    manifest = (out / "MANIFEST.json").read_text(encoding="utf-8")
    assert str(root) not in manifest  # no absolute local paths
