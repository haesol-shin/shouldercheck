"""Command line entry point for `shck`."""

import argparse
import json
import posixpath
import sys
from pathlib import Path

from shouldercheck import __version__
from shouldercheck.memory.find import InputError, render_text, run_find
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
    find.add_argument("--neighbors", type=int, help="links shown per direction (default: profile)")
    find.add_argument("--no-cache", action="store_true", help="build the index in memory only")
    _add_root_config(find)


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
            neighbors=args.neighbors,
            use_cache=not args.no_cache,
        )
    except ConfigError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 2
    except InputError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 3
    if (args.format or cfg.format) == "json":
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(render_text(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args)
    if args.command == "find":
        return _find(args)
    parser.print_help()
    return 0
