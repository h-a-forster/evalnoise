"""Read per-sample results from other eval frameworks into a trial table.

- Inspect (``inspect_ai``) logs in JSON format. Binary ``.eval`` logs are zstd-compressed;
  convert them first with ``inspect log convert --to json`` (or ``inspect log dump``).
- lm-evaluation-harness ``samples_<task>_<date>.jsonl`` files written by ``--log_samples``.

Both map one log or samples file to one run; repeats are Inspect epochs.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from evalnoise.data import DataError, to_trials

# Inspect's string score values (inspect_ai.scorer: CORRECT, INCORRECT, PARTIAL, NOANSWER).
_INSPECT_STRINGS = {"C": 1.0, "I": 0.0, "P": 0.5, "N": 0.0}
_TRUTHY = {"yes": 1.0, "true": 1.0, "no": 0.0, "false": 0.0}


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        v = float(value)
    elif isinstance(value, str):
        s = value.strip()
        if s in _INSPECT_STRINGS:
            return _INSPECT_STRINGS[s]
        if s.lower() in _TRUTHY:
            return _TRUTHY[s.lower()]
        try:
            v = float(s)
        except ValueError:
            raise DataError(f"{where}: cannot read score {value!r} as a number") from None
    else:
        raise DataError(f"{where}: score of type {type(value).__name__} is not a number")
    if not math.isfinite(v):
        raise DataError(f"{where}: non-finite score {value!r}")
    return v


def from_inspect(
    paths: Iterable[str | Path],
    *,
    scorer: str | None = None,
    metric: str | None = None,
    arm: str | None = None,
) -> pd.DataFrame:
    """Trials from Inspect JSON logs: item = sample id, arm = model, run = log, repeat = epoch.

    ``scorer`` picks a scorer when samples have several; ``metric`` picks a key when a
    score value is a dict. Samples that errored without a score are skipped and counted in
    ``attrs["skipped_errored"]``; any other missing score is an error.
    """
    rows: list[dict[str, Any]] = []
    skipped = 0
    tasks: set[str] = set()
    for path in map(Path, paths):
        if path.suffix == ".eval":
            raise DataError(
                f"{path.name}: binary .eval logs are not supported; run "
                "'inspect log convert --to json' first"
            )
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataError(f"{path.name}: {exc}") from None
        if not isinstance(log, dict) or "eval" not in log:
            raise DataError(f"{path.name}: not an Inspect log (no 'eval' field)")
        if log.get("status") not in (None, "success"):
            raise DataError(f"{path.name}: log status is {log.get('status')!r}, not 'success'")
        samples = log.get("samples")
        if not samples:
            raise DataError(f"{path.name}: no samples in the log")
        ev = log["eval"]
        task = str(ev.get("task", ""))
        tasks.add(task)
        run = str(ev.get("run_id") or ev.get("eval_id") or path.stem)
        label = arm or str(ev.get("model", ""))
        if not label:
            raise DataError(f"{path.name}: no model in the log; pass an arm label")
        for s in samples:
            where = f"{path.name}: sample {s.get('id')!r} epoch {s.get('epoch')}"
            scores = s.get("scores") or {}
            if not scores:
                if s.get("error"):
                    skipped += 1
                    continue
                raise DataError(f"{where}: no scores")
            name = scorer
            if name is None:
                if len(scores) != 1:
                    raise DataError(f"{where}: several scorers {sorted(scores)}; pick one")
                name = next(iter(scores))
            if name not in scores:
                raise DataError(f"{where}: no scorer {name!r} (have {sorted(scores)})")
            value = scores[name].get("value") if isinstance(scores[name], dict) else None
            if isinstance(value, dict):
                if metric is None or metric not in value:
                    raise DataError(f"{where}: score has keys {sorted(value)}; pick a metric")
                value = value[metric]
            rows.append(
                {
                    "task": task,
                    "item": str(s.get("id")),
                    "arm": label,
                    "run": run,
                    "repeat": int(s.get("epoch") or 1) - 1,
                    "score": _number(value, where),
                }
            )
    if not rows:
        raise DataError("no scored samples")
    frame = pd.DataFrame(rows)
    if len(tasks) > 1:
        frame["item"] = frame["task"] + "/" + frame["item"]
    out = to_trials(frame.drop(columns="task"))
    out.attrs["skipped_errored"] = skipped
    return out


_LM_EVAL_NAME = re.compile(r"^samples_(?P<task>.+)_(?P<date>\d{4}-\d{2}-\d{2}T[\w.\-]+)$")


def from_lm_eval(
    paths: Iterable[str | Path],
    *,
    metric: str | None = None,
    filter_name: str | None = None,
    arm: str | None = None,
) -> pd.DataFrame:
    """Trials from lm-eval ``samples_<task>_<date>.jsonl`` files.

    item = ``<task>/<doc_id>``, run = the file's date stamp, arm = ``arm`` or the parent
    directory (lm-eval names it after the model). ``metric`` defaults to the only metric
    logged; ``filter_name`` is required when a file holds several filters.
    """
    rows: list[dict[str, Any]] = []
    for path in map(Path, paths):
        m = _LM_EVAL_NAME.match(path.stem)
        if not m:
            raise DataError(f"{path.name}: expected a samples_<task>_<date>.jsonl file")
        task, run = m["task"], m["date"]
        label = arm or path.parent.name
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        try:
            docs = [json.loads(ln) for ln in lines]
        except json.JSONDecodeError as exc:
            raise DataError(f"{path.name}: invalid JSON ({exc.msg})") from None
        filters = {str(d.get("filter")) for d in docs}
        if filter_name is None and len(filters) > 1:
            raise DataError(f"{path.name}: several filters {sorted(filters)}; pick one")
        for d in docs:
            if filter_name is not None and str(d.get("filter")) != filter_name:
                continue
            where = f"{path.name}: doc {d.get('doc_id')}"
            if "doc_id" not in d:
                raise DataError(f"{where}: no doc_id")
            name = metric
            if name is None:
                logged = d.get("metrics") or []
                if len(logged) != 1:
                    raise DataError(f"{where}: metrics {logged}; pick one")
                name = logged[0]
            if name not in d:
                raise DataError(f"{where}: no metric {name!r}")
            value = d[name]
            if isinstance(value, (list, tuple, dict)):
                raise DataError(f"{where}: {name} is aggregated at corpus level, not per item")
            rows.append(
                {
                    "item": f"{task}/{d['doc_id']}",
                    "arm": label,
                    "run": run,
                    "score": _number(value, where),
                }
            )
    if not rows:
        raise DataError("no samples matched")
    return to_trials(pd.DataFrame(rows))
