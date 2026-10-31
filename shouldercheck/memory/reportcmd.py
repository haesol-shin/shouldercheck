"""Command-line glue for `shck report`."""

import argparse
from pathlib import Path

from shouldercheck.memory import report
from shouldercheck.memory.cases import CaseSet, read_cases
from shouldercheck.memory.qlog import log_dir
from shouldercheck.memory.settings import eval_settings, find_settings, resolve_dir
from shouldercheck.records.config import Config


def run_report_command(cfg: Config, args: argparse.Namespace) -> dict:
    options = eval_settings(cfg)
    folder = resolve_dir(options.dir, cfg, cfg.root) if options.dir else None
    ledger = args.ledger or (folder / "ledger.jsonl" if folder else None)
    case_set: CaseSet | None = None
    if ledger is not None and (args.ledger or ledger.is_file()):
        case_set = read_cases(ledger, "ledger")
    paths = list(args.runs) if args.runs else ([folder / "runs"] if folder else [])
    runs = report.load_runs(p for p in paths if args.runs or p.exists())
    log = report.read_log(log_dir(cfg, find_settings(cfg)))
    return report.build(case_set, runs, [Path(p) for p in args.audit], log)
