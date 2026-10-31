"""Command line entry point for `shck`."""

import argparse
import json
import posixpath
import sys
from pathlib import Path

from shouldercheck import __version__
from shouldercheck.memory.cases import CaseError
from shouldercheck.memory.evalcmd import render_compare_text, run_eval_command
from shouldercheck.memory.evalrun import render_run_text
from shouldercheck.memory.find import SCOPES, InputError, render_text, run_find
from shouldercheck.memory.indexrun import run_index
from shouldercheck.memory.qlog import identify, log_query
from shouldercheck.memory.settings import find_settings
from shouldercheck.memory.snapshot import SnapshotError
from shouldercheck.records.checks import CHECKS
from shouldercheck.records.config import FAIL_ON, FORMATS, ConfigError, load_config
from shouldercheck.records.report import run_check
from shouldercheck.records.suppress import IGNORE_CHECK


def _names(value: str) -> set[str]:
    names = {name.strip() for name in value.split(",") if name.strip()}
    unknown = sorted(names - {*CHECKS, IGNORE_CHECK})
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown check: {', '.join(unknown)}")
    return names


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shck", description=__doc__)
    parser.add_argument("--version", action="version", version=f"shck {__version__}")
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser(
        "check",
        help="report broken structure in a Markdown record base (read-only)",
        description="List candidates with paths. Never edits, moves or deletes.",
    )
    check.add_argument("--root", type=Path, help="record base folder (default: from config or cwd)")
    check.add_argument("--config", type=Path, help="profile file (default: shck.toml up the tree)")
    check.add_argument("--only", type=_names, help="comma-separated checks to run")
    check.add_argument("--skip", type=_names, help="comma-separated checks to leave out")
    check.add_argument("--format", choices=FORMATS, help="output format (default: text)")
    check.add_argument("--max", type=int, default=20, help="rows per check in text mode")
    check.add_argument(
        "--fail-on", choices=FAIL_ON, help="exit 1 at this severity (default: never)"
    )
    check.add_argument("--baseline", type=Path, help="earlier JSON report; its findings are muted")
    check.add_argument(
        "--paths", nargs="+", metavar="PATH", help="list findings only for these files or folders"
    )
    _add_find(sub)
    _add_index(sub)
    _add_eval(sub)
    return parser


def _add_root_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, help="record base folder (default: from config or cwd)"
    )
    parser.add_argument("--config", type=Path, help="profile file (default: shck.toml up the tree)")


def _add_find(sub: "argparse._SubParsersAction") -> None:
    find = sub.add_parser(
        "find",
        help="find records about a topic, ranked, with their linked neighbours (read-only)",
        description="Rank records by weighted fields. Writes only the derived index.",
    )
    find.add_argument("query", nargs="+", help="words to look for")
    find.add_argument("--limit", type=int, default=10, help="records to return (default: 10)")
    find.add_argument("--format", choices=FORMATS, help="output format (default: from profile)")
    find.add_argument("--scope", choices=SCOPES, default="all", help="records, transcript or all")
    find.add_argument("--neighbors", type=int, help="links shown per direction (default: profile)")
    find.add_argument("--caller", help="who is asking, e.g. hermes or omp (default: $SHCK_CALLER)")
    find.add_argument("--session", help="session id for the query log (default: $SHCK_SESSION)")
    find.add_argument("--no-log", action="store_true", help="do not append to the query log")
    find.add_argument("--no-cache", action="store_true", help="build the index in memory only")
    _add_root_config(find)


def _add_index(sub: "argparse._SubParsersAction") -> None:
    index = sub.add_parser(
        "index",
        help="generate the root map and per-section indexes (writes only generated files)",
        description="Write generated files that differ. Never edits a hand-written file.",
    )
    index.add_argument("--check", action="store_true", help="write nothing; exit 1 if stale")
    index.add_argument("--diff", action="store_true", help="print the unified diff")
    index.add_argument("--adopt", action="store_true", help="take over an unmarked map file once")
    index.add_argument("--format", choices=FORMATS, help="output format (default: text)")
    _add_root_config(index)


def _add_eval(sub: "argparse._SubParsersAction") -> None:
    ev = sub.add_parser(
        "eval",
        help="measure where the expected record lands for each case (prints, never writes)",
        description="Run a case file, or `eval compare A.json B.json` to pair two runs.",
    )
    ev.add_argument("operands", nargs="*", metavar="compare A.json B.json")
    ev.add_argument("--set", dest="case_set", default="ledger", help="ledger, probes or a file")
    ev.add_argument("--snapshot", help="git commit to search for every case")
    ev.add_argument("--git-dir", type=Path, help="history repository for snapshots")
    ev.add_argument("--live", action="store_true", help="search the live tree, ignore snapshots")
    ev.add_argument("--k", type=int, default=3, help="hit rank for losses and wins (default: 3)")
    ev.add_argument("--baseline", type=Path, help="earlier eval run (JSON)")
    ev.add_argument(
        "--abstain-below", type=float, help="top score under which no record is claimed"
    )
    ev.add_argument("--gate", action="store_true", help="exit 1 when a must_pass case regresses")
    ev.add_argument("--format", choices=FORMATS, help="output format (default: json)")
    _add_root_config(ev)


def _load_baseline(path: Path) -> set[str]:
    """Fingerprints of an earlier JSON report; shck never writes one itself."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {finding["fingerprint"] for finding in data["findings"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ConfigError(f"cannot use baseline {path.name}: {exc}") from exc


def _root_relative(paths: list[str], root: Path, cwd: Path) -> tuple[str, ...]:
    """Accept paths relative to the cwd, absolute, or already relative to the root."""
    result = []
    for given in paths:
        absolute = (cwd / given).resolve()
        try:
            rel = absolute.relative_to(root).as_posix()
        except ValueError:
            rel = posixpath.normpath(given)
        result.append("" if rel == "." else rel.rstrip("/"))
    return tuple(result)


def _check(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        cfg = load_config(args.config, args.root, cwd)
        baseline = _load_baseline(args.baseline) if args.baseline else None
    except ConfigError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 2
    paths = _root_relative(args.paths, cfg.root, cwd) if args.paths else None
    report = run_check(cfg, args.only, args.skip, baseline, paths)
    if (args.format or cfg.format) == "json":
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(report.render_text(max(args.max, 0)))
    return report.exit_code(args.fail_on or cfg.fail_on)


def _find(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config, args.root, Path.cwd())
        result = run_find(
            cfg,
            " ".join(args.query),
            limit=max(args.limit, 0),
            scope=args.scope,
            neighbors=args.neighbors,
            use_cache=not args.no_cache,
        )
    except ConfigError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 2
    except InputError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 3
    result.caller = identify(args.caller, args.session)[0]
    if not args.no_log:
        log_query(
            cfg,
            find_settings(cfg),
            result,
            caller=args.caller,
            session=args.session,
            scope=args.scope,
            limit=max(args.limit, 0),
        )
    if (args.format or cfg.format) == "json":
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(render_text(result))
    return 0


def _index(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config, args.root, Path.cwd())
        report = run_index(cfg, check=args.check, diff=args.diff, adopt=args.adopt)
    except ConfigError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 2
    except InputError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 3
    if (args.format or cfg.format) == "json":
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(report.render_text())
    return report.exit_code


def _eval(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config, args.root, Path.cwd())
        run = run_eval_command(cfg, args)
    except ConfigError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 2
    except (InputError, CaseError, SnapshotError) as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 3
    fmt = args.format or ("text" if run["kind"] == "compare" else "json")
    if fmt == "json":
        print(json.dumps(run, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(
            render_compare_text(run) if run["kind"] == "compare" else render_run_text(run)
        )
    gate = run.get("gate")
    return 1 if gate and not gate["passed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args)
    if args.command == "find":
        return _find(args)
    if args.command == "index":
        return _index(args)
    if args.command == "eval":
        return _eval(args)
    parser.print_help()
    return 0
