import json

import pytest

from evalnoise.adapters import from_inspect, from_lm_eval
from evalnoise.data import DataError


def _inspect_log(path, model="openai/m", run="run1", task="t", samples=None, status="success"):
    samples = samples or [
        {"id": 1, "epoch": 1, "scores": {"match": {"value": "C"}}},
        {"id": 1, "epoch": 2, "scores": {"match": {"value": "I"}}},
        {"id": "b", "epoch": 1, "scores": {"match": {"value": 0.5}}},
        {"id": "c", "epoch": 1, "error": {"message": "boom"}},
    ]
    log = {
        "version": 2,
        "status": status,
        "eval": {"task": task, "model": model, "run_id": run},
        "samples": samples,
    }
    path.write_text(json.dumps(log), encoding="utf-8")
    return path


def test_inspect_json(tmp_path):
    df = from_inspect(
        [
            _inspect_log(tmp_path / "a.json"),
            _inspect_log(tmp_path / "b.json", model="x/y", run="r2"),
        ]
    )
    assert len(df) == 6  # errored sample skipped
    assert df.attrs["skipped_errored"] == 2
    first = df[(df["arm"] == "openai/m") & (df["item"] == "1")]
    assert first["score"].tolist() == [1.0, 0.0]
    assert first["repeat"].tolist() == [0, 1]
    assert set(df["run"]) == {"run1", "r2"}


def test_inspect_errors(tmp_path):
    with pytest.raises(DataError, match="binary .eval"):
        from_inspect([tmp_path / "x.eval"])
    bad = _inspect_log(tmp_path / "s.json", status="error")
    with pytest.raises(DataError, match="status"):
        from_inspect([bad])
    two = _inspect_log(
        tmp_path / "two.json",
        samples=[{"id": 1, "epoch": 1, "scores": {"a": {"value": 1}, "b": {"value": 0}}}],
    )
    with pytest.raises(DataError, match="several scorers"):
        from_inspect([two])
    assert from_inspect([two], scorer="b")["score"].tolist() == [0.0]
    dict_score = _inspect_log(
        tmp_path / "d.json",
        samples=[{"id": 1, "epoch": 1, "scores": {"s": {"value": {"acc": 1, "f1": 0.5}}}}],
    )
    with pytest.raises(DataError, match="pick a metric"):
        from_inspect([dict_score])
    assert from_inspect([dict_score], metric="f1")["score"].tolist() == [0.5]
    weird = _inspect_log(
        tmp_path / "w.json", samples=[{"id": 1, "epoch": 1, "scores": {"s": {"value": "maybe"}}}]
    )
    with pytest.raises(DataError, match="cannot read"):
        from_inspect([weird])


def _samples(path, docs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")
    return path


def test_lm_eval(tmp_path):
    docs = [
        {"doc_id": i, "filter": "none", "metrics": ["acc"], "acc": float(i % 2)} for i in range(4)
    ]
    p = _samples(tmp_path / "model__x" / "samples_arc_easy_2026-10-01T10-00-00.123.jsonl", docs)
    df = from_lm_eval([p])
    assert df["item"].tolist() == ["arc_easy/0", "arc_easy/1", "arc_easy/2", "arc_easy/3"]
    assert set(df["arm"]) == {"model__x"}
    assert set(df["run"]) == {"2026-10-01T10-00-00.123"}
    assert df["score"].tolist() == [0.0, 1.0, 0.0, 1.0]


def test_lm_eval_errors(tmp_path):
    with pytest.raises(DataError, match="samples_<task>_<date>"):
        from_lm_eval([_samples(tmp_path / "results.jsonl", [])])
    two_filters = [
        {"doc_id": 0, "filter": "a", "metrics": ["em"], "em": 1},
        {"doc_id": 0, "filter": "b", "metrics": ["em"], "em": 0},
    ]
    p = _samples(tmp_path / "m" / "samples_gsm_2026-10-01T10-00-00.jsonl", two_filters)
    with pytest.raises(DataError, match="several filters"):
        from_lm_eval([p])
    assert from_lm_eval([p], filter_name="b")["score"].tolist() == [0.0]
    corpus = [{"doc_id": 0, "filter": "none", "metrics": ["bleu"], "bleu": ["ref", "pred"]}]
    p2 = _samples(tmp_path / "m" / "samples_wmt_2026-10-01T10-00-00.jsonl", corpus)
    with pytest.raises(DataError, match="corpus level"):
        from_lm_eval([p2])
