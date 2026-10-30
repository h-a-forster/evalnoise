"""Build the committed per-trial tables from source checkouts (configs/sources.toml).

Each ``[[table]]`` entry names an output CSV, an extractor and its source paths. Paths are
relative to the config file's parent directory's parent (the repository root), so the
default config expects the source repositories checked out next to this one. Output CSVs
carry no local paths; ``MANIFEST.json`` records source repository, commit and per-file
sha256 so the tables can be traced and regenerated.
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

from evalnoise.data import DataError
from evalnoise.sources import Extract, agent_ab, git_commit, git_tracked, mm_arena, ruleproof

EXTRACTORS = ("mm-arena", "agent-ab", "ruleproof")


def load_config(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    path = Path(path)
    try:
        cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DataError(f"{path}: {exc}") from None
    tables = cfg.get("table")
    if not isinstance(tables, list) or not tables:
        raise DataError(f"{path}: no [[table]] entries")
    names = set()
    for t in tables:
        for key in ("name", "extractor", "repo", "paths"):
            if key not in t:
                raise DataError(f"{path}: table entry missing {key!r}: {t}")
        if t["extractor"] not in EXTRACTORS:
            raise DataError(f"{path}: unknown extractor {t['extractor']!r}")
        if t["name"] in names:
            raise DataError(f"{path}: duplicate table name {t['name']!r}")
        if not all(ch.isalnum() or ch in "-_" for ch in t["name"]):
            raise DataError(f"{path}: table name {t['name']!r} must be alphanumeric, - or _")
        if t["extractor"] == "ruleproof":
            runs = t.get("runs")
            if not isinstance(runs, list) or not runs or not all(isinstance(r, str) for r in runs):
                raise DataError(f'{path}: table {t["name"]!r} needs runs = ["run id", ...]')
            if not isinstance(t.get("rename", {}), dict):
                raise DataError(f"{path}: table {t['name']!r}: rename must be a table")
        names.add(t["name"])
    return path.resolve().parent.parent, tables


def run_extract(config: Path, out_dir: Path, only: list[str] | None = None) -> dict[str, Any]:
    """Extract every table (or ``only`` these), write CSVs and update the manifest."""
    root, tables = load_config(config)
    if only:
        unknown = set(only) - {t["name"] for t in tables}
        if unknown:
            raise DataError(f"unknown table(s): {', '.join(sorted(unknown))}")
        tables = [t for t in tables if t["name"] in only]
    # Validate every source path before writing anything.
    for t in tables:
        for p in t["paths"]:
            if not (root / p).exists():
                raise DataError(f"table {t['name']}: source path {p!r} not found under {root.name}")
    # Extract everything before writing, so a failing table leaves every file unchanged.
    extracted = []
    for t in tables:
        paths = [root / p for p in t["paths"]]
        extracted.append((t, paths, _extract_one(t, paths)))
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "MANIFEST.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for t, paths, ex in extracted:
        csv_path = out_dir / f"{t['name']}.csv"
        tmp = csv_path.with_suffix(".csv.tmp")
        ex.table.to_csv(tmp, index=False, lineterminator="\n", float_format="%.10g")
        os.replace(tmp, csv_path)
        commit = git_commit(paths[0])
        tracked = git_tracked(paths[0])
        files: dict[str, str] = {}
        untracked: list[str] = []
        for abs_path, digest in ex.files.items():
            key = _relative(Path(abs_path), root)
            files[key] = digest
            if tracked is not None and Path(abs_path) not in tracked:
                untracked.append(key)
        manifest[t["name"]] = {
            "extractor": t["extractor"],
            "repo": t["repo"],
            "commit": commit,
            "source_paths": list(t["paths"]),
            "description": t.get("description", ""),
            "rows": int(len(ex.table)),
            "excluded": ex.excluded,
            "notes": ex.notes,
            "files": dict(sorted(files.items())),
            # Files not committed in the source repository at `commit` (e.g. new runs).
            "untracked_files": sorted(untracked) if tracked is not None else None,
        }
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, manifest_path)
    return manifest


def _relative(path: Path, root: Path) -> str:
    """Path relative to the repository root, never absolute (fall back to the file name)."""
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:  # a different drive on Windows
        return path.name


def _extract_one(t: dict[str, Any], paths: list[Path]) -> Extract:
    kind = t["extractor"]
    if kind == "mm-arena":
        return mm_arena(paths, reference=t.get("reference", "bayes"))
    if kind == "agent-ab":
        if len(paths) != 1:
            raise DataError(f"table {t['name']}: agent-ab takes one run directory")
        return agent_ab(paths[0], run_label=t.get("run_label"))
    if len(paths) != 1:
        raise DataError(f"table {t['name']}: ruleproof takes one results directory")
    return ruleproof(paths[0], runs=t["runs"], rename=t.get("rename", {}))
