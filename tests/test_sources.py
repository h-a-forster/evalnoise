import json
import shutil
import subprocess

import pytest

from evalnoise.data import DataError
from evalnoise.extract import run_extract
from evalnoise.sources import agent_ab, mm_arena, ruleproof, sha256


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


def test_malformed_records_are_data_errors(arena, tmp_path):
    # Regression: missing fields raised raw KeyErrors, and prior_std 0 was silently 1.
    _, a = arena
    bad = _trace("claude-cli:m@high", "g1", 0, 1.0)
    del bad["seed"]
    _write(a / "claude-cli_m@high.jsonl", [bad])
    with pytest.raises(DataError, match="record 1"):
        mm_arena([a])
    _write(a / "claude-cli_m@high.jsonl", [_trace("claude-cli:m@high", "g1", 0, 1.0, prior_std=0)])
    with pytest.raises(DataError, match="prior_std"):
        mm_arena([a])
    d = tmp_path / "exp"
    d.mkdir()
    _write(d / "trials.jsonl", [{"arm": "a", "repeat": 0, "status": "pass"}])
    with pytest.raises(DataError, match="record 1"):
        agent_ab(d)
    res = tmp_path / "results"
    _rp(res, "p2", "p2", "y", "t1", 1)
    (res / "p2" / "trials" / "y" / "t1" / "r1.json").write_text("{", encoding="utf-8")
    with pytest.raises(DataError, match="r1.json"):
        ruleproof(res, runs=["p2"])


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
    # Regression: a later table failing left earlier CSVs rewritten and the manifest stale.
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    _write(a / "claude-cli_m@high.jsonl", [_trace("claude-cli:m@high", "g1", 0, 9.0)])
    exp = root / "exp"
    exp.mkdir()
    _write(exp / "trials.jsonl", [{"task": "t", "arm": "a", "repeat": 0, "status": "pass"}] * 2)
    cfg.write_text(
        '[[table]]\nname = "arena"\nextractor = "mm-arena"\nrepo = "x"\npaths = ["../a"]\n'
        '[[table]]\nname = "ab"\nextractor = "agent-ab"\nrepo = "x"\npaths = ["../exp"]\n',
        encoding="utf-8",
    )
    with pytest.raises(DataError, match="duplicate"):
        run_extract(cfg, out)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before
    cfg.write_text(
        '[[table]]\nname = "rp"\nextractor = "ruleproof"\nrepo = "x"\npaths = ["../a"]\n',
        encoding="utf-8",
    )
    with pytest.raises(DataError, match="runs"):
        run_extract(cfg, out)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_manifest_lists_files_not_committed_upstream(tmp_path, arena):
    root, a = arena

    def git(*args):
        subprocess.run(["git", "-C", str(a), *args], check=True, capture_output=True)

    git("init", "-q")
    git("add", "bayes.jsonl")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    repo = root / "repo"
    (repo / "configs").mkdir(parents=True)
    cfg = repo / "configs" / "sources.toml"
    cfg.write_text(
        '[[table]]\nname = "arena"\nextractor = "mm-arena"\nrepo = "x"\npaths = ["../a"]\n',
        encoding="utf-8",
    )
    m = run_extract(cfg, repo / "out")
    assert m["arena"]["untracked_files"] == ["../a/claude-cli_m@high.jsonl"]
    assert m["arena"]["commit"]


def test_manifest_keeps_files_from_same_named_roots_apart(tmp_path, arena):
    # Regression: keys were "<root name>/<file>", so two roots both named core-v1 collided.
    root, a = arena
    for sub in ("results", "runs"):
        d = root / sub / "core-v1"
        d.mkdir(parents=True)
        for f in a.glob("*.jsonl"):
            (d / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    repo = root / "repo"
    (repo / "configs").mkdir(parents=True)
    cfg = repo / "configs" / "sources.toml"
    cfg.write_text(
        '[[table]]\nname = "arena"\nextractor = "mm-arena"\nrepo = "x"\n'
        'paths = ["../results/core-v1", "../runs/core-v1"]\n',
        encoding="utf-8",
    )
    m = run_extract(cfg, repo / "out")
    assert sorted(m["arena"]["files"]) == [
        "../results/core-v1/bayes.jsonl",
        "../results/core-v1/claude-cli_m@high.jsonl",
        "../runs/core-v1/bayes.jsonl",
        "../runs/core-v1/claude-cli_m@high.jsonl",
    ]


def test_sha256_ignores_crlf_line_endings(tmp_path):
    # Lines placed so one CRLF straddles the 1 MiB read boundary.
    lines = [b"x" * ((1 << 20) - 1), b'{"a": 1}', b""]
    lf, crlf = tmp_path / "lf.jsonl", tmp_path / "crlf.jsonl"
    lf.write_bytes(b"\n".join(lines))
    crlf.write_bytes(b"\r\n".join(lines))
    assert sha256(crlf) == sha256(lf)
    other = tmp_path / "other.jsonl"
    other.write_bytes(b"\n".join(lines).replace(b"1", b"2"))
    assert sha256(other) != sha256(lf)
