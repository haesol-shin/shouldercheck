"""Command line entry point for `shck`."""

import argparse
import json
import sys
from pathlib import Path

from shouldercheck import __version__
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
    return parser


def _check(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config, args.root, Path.cwd())
    except ConfigError as exc:
        print(f"shck: {exc}", file=sys.stderr)
        return 2
    report = run_check(cfg, args.only, args.skip)
    if (args.format or cfg.format) == "json":
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(report.render_text(max(args.max, 0)))
    return report.exit_code(args.fail_on or cfg.fail_on)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args)
    parser.print_help()
    return 0
