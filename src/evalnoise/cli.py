"""Command-line interface: ``evalnoise components | power | extract | study | validate``."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from evalnoise import __version__
from evalnoise.data import DataError, describe, read_table, to_trials
from evalnoise.report import LABELS, fmt, fmt_ci, pct, sd, study_markdown, table

EXIT_USAGE = 2


def _ints(text: str) -> list[int]:
    try:
        vals = [int(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected comma-separated integers, got {text!r}"
        ) from None
    if not vals or min(vals) < 1:
        raise argparse.ArgumentTypeError("values must be positive integers")
    return vals


def _floats(text: str) -> list[float]:
    try:
        vals = [float(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected comma-separated numbers, got {text!r}"
        ) from None
    if not vals or any(not math.isfinite(v) or v <= 0 for v in vals):
        raise argparse.ArgumentTypeError("values must be positive numbers")
    return vals


def _level(text: str) -> float:
    v = float(text)
    if not 0 < v < 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return v


def _pair(text: str) -> tuple[str, str]:
    parts = text.split(",")
    if len(parts) != 2 or not all(p.strip() for p in parts):
        raise argparse.ArgumentTypeError(f"expected ARM_A,ARM_B, got {text!r}")
    return parts[0].strip(), parts[1].strip()


def _add_input(p: argparse.ArgumentParser, required: bool) -> None:
    g = p.add_argument_group("input")
    g.add_argument("files", nargs="+" if required else "*", type=Path, help="result file(s)")
    g.add_argument(
        "--input-format",
        choices=["auto", "table", "inspect", "lm-eval"],
        default="auto",
        help="auto: .csv/.jsonl = table, .json/.eval = Inspect log, samples_*.jsonl = lm-eval",
    )
    for name in ("item", "arm", "run", "cluster", "score"):
        g.add_argument(
            f"--{name}-col", dest=f"{name}_col", metavar="COL", help=f"column for {name}"
        )
    g.add_argument(
        "--arm-label",
        help="arm label for a table without an arm column; for Inspect and lm-eval, replaces "
        "the model name",
    )
    g.add_argument("--metric", help="metric name (Inspect dict scores, lm-eval)")
    g.add_argument("--scorer", help="Inspect scorer name when there are several")
    g.add_argument("--filter", dest="filter_name", help="lm-eval filter name")
    g.add_argument("--scale", type=float, default=1.0, help="multiply scores (e.g. 100 for pp)")
    g.add_argument("--arms", help="comma-separated arms to keep (default: all)")


def _load(args: argparse.Namespace) -> pd.DataFrame:
    from evalnoise.adapters import from_inspect, from_lm_eval

    fmt_ = args.input_format
    files: list[Path] = args.files
    if fmt_ == "auto":
        kinds = set()
        for f in files:
            if f.name.startswith("samples_") and f.suffix == ".jsonl":
                kinds.add("lm-eval")
            elif f.suffix in (".json", ".eval"):
                kinds.add("inspect")
            else:
                kinds.add("table")
        if len(kinds) != 1:
            raise DataError("mixed input formats; pass --input-format")
        fmt_ = kinds.pop()
    if fmt_ == "inspect":
        df = from_inspect(files, scorer=args.scorer, metric=args.metric, arm=args.arm_label)
        if df.attrs.get("skipped_errored"):
            print(
                f"evalnoise: note: skipped {df.attrs['skipped_errored']} errored sample(s) "
                "without a score",
                file=sys.stderr,
            )
    elif fmt_ == "lm-eval":
        df = from_lm_eval(
            files, metric=args.metric, filter_name=args.filter_name, arm=args.arm_label
        )
    else:
        cols = {k: getattr(args, f"{k}_col") for k in ("item", "arm", "run", "cluster", "score")}
        cols = {k: v for k, v in cols.items() if v}
        frames, runless = [], []
        for f in files:
            raw = read_table(f)
            frame = to_trials(raw, cols, default_arm=args.arm_label)
            frames.append(frame)
            if cols.get("run", "run") not in raw.columns:
                runless.append((f, set(frame["arm"])))
        # Files without a run column all get run "run-1": an arm in two of them would
        # silently merge two runs into one.
        for (f1, a1), (f2, a2) in itertools.combinations(runless, 2):
            if a1 & a2:
                raise DataError(
                    f"{f1.name} and {f2.name} have no run column but share arm(s) "
                    f"{', '.join(sorted(a1 & a2))}; add a run column (or --run-col)"
                )
        df = pd.concat(frames, ignore_index=True)
    if args.arms:
        keep = [a.strip() for a in args.arms.split(",") if a.strip()]
        missing = sorted(set(keep) - set(df["arm"]))
        if missing:
            raise DataError(f"arm(s) not in data: {', '.join(missing)}")
        df = df[df["arm"].isin(keep)].reset_index(drop=True)
    if args.scale != 1.0:
        if not math.isfinite(args.scale) or args.scale == 0:
            raise DataError("--scale must be a finite non-zero number")
        df = df.assign(score=df["score"] * args.scale)
    return df


# --------------------------------------------------------------------------- components


def cmd_components(args: argparse.Namespace) -> int:
    from evalnoise.components import bootstrap, estimate

    df = _load(args)
    est = estimate(df, pairs=args.pair)
    boot = None
    if args.bootstrap:
        boot = bootstrap(df, pairs=args.pair, draws=args.bootstrap, seed=args.seed)
    reml_c = None
    if args.reml:
        from evalnoise.reml import reml

        reml_c = reml(df)
    comps = est.components
    if args.json:
        out: dict[str, Any] = {
            "counts": describe(df),
            "components": comps.to_dict(),
            "run_interval": list(est.run_term.interval()),
            "arm_means": est.arm_means,
            "pairs": est.pairs,
        }
        if boot:
            out["bootstrap"] = {
                "draws": boot.draws,
                "components": boot.components,
                "pairs": boot.pairs,
            }
        if reml_c:
            out["reml"] = reml_c.to_dict()
        print(json.dumps(_jsonable(out), indent=1))
        return 0
    c = describe(df)
    print(
        f"{c['trials']} trials, {c['items']} items ({c['clusters']} clusters), {c['arms']} arm(s), "
        f"runs per arm {sorted(set(c['runs_per_arm'].values()))}, "
        f"up to {c['max_repeats_per_run']} repeats per run"
    )
    rows = []
    for name, label in LABELS.items():
        v = getattr(comps, name)
        if name in comps.absorbed:
            rows.append([label, "-", "-", f"folded into {LABELS[comps.absorbed[name]]}"])
            continue
        if not math.isfinite(v):
            rows.append([label, "-", "-", "not identified"])
            continue
        if name == "run":
            lo, hi = est.run_term.interval()
            ci, how = fmt_ci(sd(lo), sd(hi), 3), f"MLS, {est.run_term.df} df"
        elif boot:
            lo, hi = boot.components[name]
            ci, how = fmt_ci(sd(lo), sd(hi), 3), f"bootstrap, {boot.draws} draws"
        else:
            ci, how = "-", ""
        extra = f"; REML {fmt(sd(getattr(reml_c, name)), 3)}" if reml_c else ""
        rows.append([label, f"{v:.4g}", f"{fmt(sd(v), 3)} {ci}", how + extra])
    print(table(["component", "variance", "SD [95%]", "interval"], rows, "lrrl"))
    for name, p in est.pairs.items():
        print(
            f"{name}: difference {p['difference']:.4g}, item-level SE {p['se_items']:.4g}, "
            f"item x arm SD {fmt(sd(p['item_arm']), 3)} over {p['items']} items"
        )
    return 0


# --------------------------------------------------------------------------- power


def _components_arg(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in text.split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise argparse.ArgumentTypeError(f"expected name=variance, got {part!r}")
        k, v = part.split("=", 1)
        k = k.strip()
        if k not in LABELS:
            raise argparse.ArgumentTypeError(f"unknown component {k!r}; use {', '.join(LABELS)}")
        try:
            val = float(v)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{k}: not a number: {v!r}") from None
        if not math.isfinite(val) or val < 0:
            raise argparse.ArgumentTypeError(f"{k}: variance must be a non-negative number")
        out[k] = val
    if not out:
        raise argparse.ArgumentTypeError("no components given")
    return out


def cmd_power(args: argparse.Namespace) -> int:
    from evalnoise.components import Components, estimate
    from evalnoise.power import optimal_repeats, plan, resolve, tasks_needed

    if bool(args.files) == bool(args.components):
        raise DataError("give either result files or --components, not both")
    paired = not args.unpaired
    run_df = math.inf if args.run_df is None else args.run_df
    if args.components:
        given = dict(args.components)
        comps = Components(**given)  # type: ignore[arg-type]
        source = "given components"
    else:
        df = _load(args)
        est = estimate(df)
        comps = est.components
        source = f"estimated from {len(df)} trials"
        if args.run_df is None and args.run_var is None and math.isfinite(comps.run):
            # The run variance comes from these replicate runs: use its degrees of freedom.
            run_df = float(est.run_term.df)
    r = resolve(
        comps,
        run=args.run_var,
        paired=paired,
        run_df=run_df,
        design_effect=args.design_effect,
        pass_rate=args.pass_rate,
        pass_score=args.pass_score,
    )
    rows = plan(
        r,
        args.tasks,
        args.runs,
        args.repeats,
        paired=paired,
        alpha=args.alpha,
        power=args.power,
        method=args.method,
    )
    needed = []
    for target in args.mde or []:
        for nr in args.runs:
            for k in args.repeats:
                t = tasks_needed(
                    r,
                    target,
                    runs=nr,
                    repeats=k,
                    paired=paired,
                    alpha=args.alpha,
                    power=args.power,
                    method=args.method,
                )
                needed.append({"mde": target, "runs": nr, "repeats": k, "tasks": t})
    k_opt = (
        [
            {"runs": nr, "repeats": optimal_repeats(r, runs=nr, task_cost=args.task_cost)}
            for nr in args.runs
        ]
        if args.task_cost is not None
        else None
    )
    if args.json:
        print(
            json.dumps(
                _jsonable(
                    {
                        "source": source,
                        "paired": paired,
                        "alpha": args.alpha,
                        "power": args.power,
                        "components": vars(r) | {"notes": list(r.notes)},
                        "run_df": r.run_df,
                        "grid": rows,
                        "tasks_needed": needed,
                        "optimal_repeats": k_opt,
                    }
                ),
                indent=1,
            )
        )
        return 0
    kind = "paired" if paired else "unpaired"
    print(
        f"{kind} comparison of two arms, alpha {args.alpha}, power {args.power}, {source}; "
        f"SD item {sd(r.item):.3g}, item x arm {sd(r.item_arm):.3g}, run {sd(r.run):.3g}, "
        f"item x run {sd(r.item_run):.3g}, within {sd(r.within):.3g}"
    )
    for note in r.notes:
        print(f"note: {note}")
    print(
        table(
            ["tasks", "runs", "repeats", "trials/arm", "SE", "MDE", "naive FPR"],
            [
                [
                    str(x["tasks"]),
                    str(x["runs"]),
                    str(x["repeats"]),
                    str(x["trials_per_arm"]),
                    f"{x['se']:.3g}",
                    f"{x['mde']:.3g}",
                    pct(x["naive_fpr"]),
                ]
                for x in rows
            ],
        )
    )
    print("naive FPR: false-positive rate of a test that ignores run effects (nominal alpha).")
    for x in needed:
        t = x["tasks"]
        what = f"{t} tasks per arm" if t is not None else "unreachable (add runs, not tasks)"
        print(f"MDE {x['mde']:g} with {x['runs']} run(s) x {x['repeats']} repeat(s): {what}")
    for x in k_opt or []:
        print(f"cost-optimal repeats per item per run with {x['runs']} run(s): {x['repeats']:.2f}")
    return 0


# --------------------------------------------------------------------------- study


def cmd_extract(args: argparse.Namespace) -> int:
    from evalnoise.extract import run_extract

    m = run_extract(args.config, args.out, args.only)
    for name, info in m.items():
        if args.only and name not in args.only:
            continue
        print(f"{name}: {info['rows']} trials, excluded {info['excluded'] or 'none'}")
    return 0


def cmd_study(args: argparse.Namespace) -> int:
    from evalnoise.study import run_study

    units = run_study(args.config, args.out, args.profile, args.only, args.force)
    if not args.only:
        (args.out / "summary.md").write_text(study_markdown(units, args.profile), encoding="utf-8")
        print(f"wrote {args.out / 'summary.md'}")
    print(f"{len(units)} dataset(s); units in {args.out / 'units'}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from evalnoise.validate import run_validation, validation_markdown

    res = run_validation(args.out, args.profile, args.only, args.force)
    if not args.only:
        (args.out / "summary.md").write_text(
            validation_markdown(res, args.profile), encoding="utf-8"
        )
    print(validation_markdown(res, args.profile))
    return 0


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if hasattr(x, "item"):
        return _jsonable(x.item())
    return x


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="evalnoise", description=__doc__)
    p.add_argument("--version", action="version", version=f"evalnoise {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("components", help="estimate variance components from per-trial results")
    _add_input(c, required=True)
    c.add_argument("--pair", type=_pair, action="append", default=[], help="ARM_A,ARM_B to compare")
    c.add_argument("--bootstrap", type=int, default=1000, help="bootstrap draws (0 = none)")
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--reml", action="store_true", help="also fit REML (slower)")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_components)

    w = sub.add_parser("power", help="MDE and tasks/repeats/runs needed for a comparison")
    _add_input(w, required=False)
    w.add_argument("--components", type=_components_arg, help="item=V,item_arm=V,run=V,...")
    w.add_argument("--tasks", type=_ints, default=[10, 20, 30, 50, 100, 200])
    w.add_argument("--runs", type=_ints, default=[1])
    w.add_argument("--repeats", type=_ints, default=[1, 3])
    w.add_argument("--mde", type=_floats, help="target effect(s): report tasks needed")
    w.add_argument("--alpha", type=_level, default=0.05)
    w.add_argument("--power", type=_level, default=0.8)
    w.add_argument("--unpaired", action="store_true", help="arms see different items")
    w.add_argument(
        "--run-var",
        type=float,
        help="run variance to assume (required when the data has one run per arm; 0 = none)",
    )
    w.add_argument(
        "--run-df",
        type=float,
        help="degrees of freedom of the run-variance estimate (default: from the data's "
        "replicate runs; inf when the variance is given)",
    )
    w.add_argument(
        "--design-effect",
        type=float,
        default=1.0,
        help="multiply the item-level variance (clustered items; at least 1)",
    )
    w.add_argument(
        "--pass-rate",
        type=float,
        help="pass/fail scores: base pass rate (0-1); the shifted arm's variance is taken at "
        "its own rate where larger, and the MDE is the larger of gain and loss",
    )
    w.add_argument(
        "--pass-score", type=float, default=1.0, help="score of a pass (e.g. 100 for pp)"
    )
    w.add_argument("--method", choices=["t", "z"], default="t")
    w.add_argument("--task-cost", type=float, help="cost of a new task in trials: optimal repeats")
    w.add_argument("--json", action="store_true")
    w.set_defaults(func=cmd_power)

    e = sub.add_parser("extract", help="rebuild results/trials from source checkouts")
    e.add_argument("--config", type=Path, default=Path("configs/sources.toml"))
    e.add_argument("--out", type=Path, default=Path("results/trials"))
    e.add_argument("--only", nargs="+")
    e.set_defaults(func=cmd_extract)

    s = sub.add_parser("study", help="run the variance-components study (resumable)")
    s.add_argument("--config", type=Path, default=Path("configs/study.toml"))
    s.add_argument("--out", type=Path, default=Path("results/study"))
    s.add_argument("--profile", default="quick")
    s.add_argument("--only", nargs="+")
    s.add_argument("--force", action="store_true", help="recompute finished units")
    s.set_defaults(func=cmd_study)

    v = sub.add_parser("validate", help="Monte Carlo checks of the planner (resumable)")
    v.add_argument("--out", type=Path, default=Path("results/validation"))
    v.add_argument("--profile", default="quick", choices=["quick", "full"])
    v.add_argument("--only", nargs="+")
    v.add_argument("--force", action="store_true")
    v.set_defaults(func=cmd_validate)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (DataError, ValueError) as exc:
        print(f"evalnoise: error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
