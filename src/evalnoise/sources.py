"""Extract per-trial tables from published agent-eval result directories.

Each extractor reads one source layout and returns a trial table with the schema columns
plus ``harness`` (agent/CLI version when recorded) and one column per outcome. Nothing here
calls a model or the network. Supported layouts:

- mm-arena trace files (``<agent>.jsonl``, one episode per line);
- agent-ab run directories (``trials.jsonl``), which overclaim also publishes;
- the ruleproof compliance benchmark (``bench/results/<run>/trials/<arm>/<task>/r<k>.json``).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from evalnoise.data import DataError

META = ("item", "cluster", "arm", "run", "repeat", "harness")


@dataclass
class Extract:
    """A trial table plus provenance."""

    table: pd.DataFrame
    files: dict[str, str] = field(default_factory=dict)  # absolute path -> sha256
    excluded: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit(path: Path) -> str | None:
    """Commit of the repository containing ``path``, or None (no git, not a repo)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def git_tracked(path: Path) -> set[Path] | None:
    """Files tracked by git in the repository containing ``path`` (None without git)."""
    try:
        top = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if top.returncode != 0:
            return None
        root = Path(top.stdout.strip())
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {(root / f).resolve() for f in out.stdout.split("\0") if f}


def iter_jsonl(path: Path, excluded: dict[str, int]) -> Iterator[dict]:
    """Yield JSON objects; tolerate only a truncated last line (a file still being written)."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if lineno == len(lines) and not line.endswith("\n"):
                excluded["truncated last line"] = excluded.get("truncated last line", 0) + 1
                continue
            raise DataError(f"{path.name}:{lineno}: invalid JSON") from None
        if not isinstance(row, dict):
            raise DataError(f"{path.name}:{lineno}: expected a JSON object")
        yield row


def _bump(d: dict[str, int], key: str) -> None:
    d[key] = d.get(key, 0) + 1


# --------------------------------------------------------------------------- mm-arena

_REPLICATE = re.compile(r"^(?P<setup>.+)#r(?P<n>\d+)$")


def mm_arena(roots: Iterable[Path], reference: str = "bayes") -> Extract:
    """LLM episodes from mm-arena trace directories, scored as edge captured (pp).

    ``score`` is ``100 * xpnl_sd / mean(reference xpnl_sd)`` over the reference agent's
    episodes, so an arm's mean score over the full suite equals its edge captured %.
    Item = episode (game, seed); cluster = game, as in mm-arena's own bootstrap. Replicate
    runs are agents named ``<setup>#rN``; the unsuffixed agent is run ``r1``. The same
    episode found in several roots must be identical, else extraction fails.
    """
    roots = [Path(r) for r in roots]
    out = Extract(table=pd.DataFrame())
    episodes: dict[tuple[str, str, str, int], dict] = {}
    ref: dict[tuple[str, int], float] = {}
    for root in roots:
        if not root.is_dir():
            raise DataError(f"{root}: not a directory")
        files = sorted(root.glob("*.jsonl"))
        for path in files:
            agent_file = path.stem
            is_ref = agent_file == reference
            if not (is_ref or agent_file.startswith(("claude-cli_", "anthropic_"))):
                continue
            out.files[str(path.resolve())] = sha256(path)
            for t in iter_jsonl(path, out.excluded):
                gid, seed = str(t["game"]["id"]), int(t["seed"])
                if t.get("status") != "ok":
                    _bump(out.excluded, f"status {t.get('status')}")
                    continue
                prior_std = float(t["game"]["prior_std"]) or 1.0
                xsd = float(t["xpnl"]) / prior_std
                if is_ref:
                    old = ref.setdefault((gid, seed), xsd)
                    if not math.isclose(old, xsd, rel_tol=1e-12, abs_tol=1e-12):
                        raise DataError(f"reference episode {gid}/{seed} differs between roots")
                    continue
                agent = str(t["agent"])
                m = _REPLICATE.match(agent)
                setup, run = (m["setup"], f"r{m['n']}") if m else (agent, "r1")
                key = (setup, run, gid, seed)
                row = {
                    "item": f"{gid}/s{seed}",
                    "cluster": gid,
                    "arm": setup,
                    "run": run,
                    "repeat": 0,
                    "harness": str((t.get("provenance") or {}).get("harness") or "unrecorded"),
                    "family": str(t["game"]["family"]),
                    "variant": str(t["game"]["variant"]),
                    "xpnl_sd": xsd,
                }
                prev = episodes.get(key)
                if prev is not None:
                    if not math.isclose(prev["xpnl_sd"], xsd, rel_tol=1e-12, abs_tol=1e-12):
                        raise DataError(f"{setup} {run} {gid}/{seed}: conflicting copies")
                    _bump(out.excluded, "duplicate copy (identical)")
                    continue
                episodes[key] = row
    if not ref:
        raise DataError(f"no reference agent {reference!r} found")
    if not episodes:
        raise DataError("no LLM episodes found")
    ref_mean = sum(ref.values()) / len(ref)
    df = pd.DataFrame(list(episodes.values()))
    missing = ~df.apply(lambda r: _episode_key(r["item"]) in ref, axis=1)
    if missing.any():
        raise DataError(f"{int(missing.sum())} episode(s) have no reference episode")
    df["edge_pp"] = 100.0 * df["xpnl_sd"] / ref_mean
    out.notes.append(
        f"edge_pp = 100 * xpnl_sd / {ref_mean:.6f} (mean {reference} xpnl_sd over {len(ref)} "
        "episodes)"
    )
    out.table = df.sort_values(["arm", "run", "item"]).reset_index(drop=True)
    return out


def _episode_key(item: str) -> tuple[str, int]:
    gid, seed = item.rsplit("/s", 1)
    return gid, int(seed)


# --------------------------------------------------------------------------- agent-ab


def agent_ab(run_dir: Path, run_label: str | None = None) -> Extract:
    """Trials of one agent-ab run directory (one run per arm, named after the directory).

    Outcomes: ``passed`` (hidden check, 0/1), ``cost_usd`` and ``log_cost``. Trials whose
    status is not pass/fail (errors, timeouts without a verdict) are excluded and counted.
    """
    run_dir = Path(run_dir)
    path = run_dir / "trials.jsonl"
    if not path.is_file():
        raise DataError(f"{path}: not found")
    out = Extract(table=pd.DataFrame())
    out.files[str(path.resolve())] = sha256(path)
    label = run_label or run_dir.name
    rows = []
    seen: set[tuple[str, str, int]] = set()
    for t in iter_jsonl(path, out.excluded):
        status = t.get("status")
        if status not in ("pass", "fail"):
            _bump(out.excluded, f"status {status}")
            continue
        key = (str(t["task"]), str(t["arm"]), int(t["repeat"]))
        if key in seen:
            raise DataError(f"{path.name}: duplicate trial {key}")
        seen.add(key)
        cost = t.get("cost_usd")
        cost = float(cost) if cost is not None else math.nan
        rows.append(
            {
                "item": key[0],
                "cluster": key[0],
                "arm": key[1],
                "run": label,
                "repeat": key[2],
                "harness": str(t.get("agent_version") or "unrecorded"),
                "passed": 1.0 if status == "pass" else 0.0,
                "cost_usd": cost,
                "log_cost": math.log(cost) if cost and cost > 0 else math.nan,
            }
        )
    if not rows:
        raise DataError(f"{path}: no scored trials")
    out.table = pd.DataFrame(rows).sort_values(["arm", "item", "repeat"]).reset_index(drop=True)
    return out


# --------------------------------------------------------------------------- ruleproof


def _verdict(rec: dict) -> tuple[object, ...]:
    report = rec.get("report") or {}
    return (report.get("summary"), rec["trial"].get("hidden_pass"), rec["trial"].get("error"))


def ruleproof(
    results_dir: Path, runs: Iterable[str], rename: dict[str, str] | None = None
) -> Extract:
    """Trials of the ruleproof compliance benchmark for the given run ids.

    Run directories also hold copies of trials from other runs; each trial is keyed by the
    ``run_id`` it records, and the copy inside its own run's directory wins. Outcomes:
    ``all_rules`` (no rule failed or unverified, 0/1), ``hidden_pass`` (0/1) and
    ``rules_failed`` (count). ``rename`` maps ``"run:arm"`` to a new arm name.
    """
    results_dir = Path(results_dir)
    wanted = list(runs)
    rename = rename or {}
    out = Extract(table=pd.DataFrame())
    chosen: dict[tuple[str, str, str, int], tuple[bool, dict, str]] = {}
    for run_dir in sorted(p for p in results_dir.iterdir() if (p / "trials").is_dir()):
        for path in sorted((run_dir / "trials").glob("*/*/r*.json")):
            rec = json.loads(path.read_text(encoding="utf-8"))
            t = rec["trial"]
            run_id = str(t["run_id"])
            if run_id not in wanted:
                continue
            key = (run_id, str(t["arm"]), str(t["task"]), int(t["rep"]))
            own = run_dir.name == run_id
            rel = path.relative_to(results_dir).as_posix()
            prev = chosen.get(key)
            if prev is not None and _verdict(prev[1]) != _verdict(rec):
                raise DataError(f"trial {key}: copies disagree ({prev[2]} vs {rel})")
            if prev is None or (own and not prev[0]):
                if prev is not None:
                    _bump(out.excluded, "copy outside its run directory")
                chosen[key] = (own, rec, rel)
            else:
                _bump(out.excluded, "copy outside its run directory")
    rows = []
    for (run_id, arm, task, rep), (_, rec, rel) in sorted(chosen.items()):
        t, report = rec["trial"], rec.get("report")
        if t.get("error") or not report:
            _bump(out.excluded, "errored or unscored")
            continue
        out.files[str((results_dir / rel).resolve())] = sha256(results_dir / rel)
        summary = report["summary"]
        rows.append(
            {
                "item": task,
                "cluster": task,
                "arm": rename.get(f"{run_id}:{arm}", arm),
                "run": run_id,
                "repeat": rep,
                "harness": str(t.get("agent_version") or "unrecorded"),
                "model": str(t.get("model") or ""),
                "all_rules": float(summary["failed"] == 0 and summary["unverified"] == 0),
                "hidden_pass": float(bool(t.get("hidden_pass"))),
                "rules_failed": float(summary["failed"]),
            }
        )
    if not rows:
        raise DataError(f"{results_dir}: no trials for runs {wanted}")
    out.table = pd.DataFrame(rows)
    return out
