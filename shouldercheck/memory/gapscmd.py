"""Command-line glue for `shck gaps`."""

import argparse

from shouldercheck.memory.gaps import analyse, audit_report, audit_template, read_audit, read_facts
from shouldercheck.memory.settings import (
    eval_settings,
    find_settings,
    gaps_settings,
    resolve_dir,
)
from shouldercheck.records.config import Config, ConfigError


def run_gaps_command(cfg: Config, args: argparse.Namespace) -> dict:
    if args.live and args.snapshot:
        raise ConfigError("--live and --snapshot cannot be combined")
    if args.sample is not None and args.sample < 1:
        raise ConfigError("--sample must be a positive number")
    options = eval_settings(cfg)
    git_dir = args.git_dir or (
        resolve_dir(options.git_dir, cfg, cfg.root) if options.git_dir else None
    )
    facts, digest = read_facts(args.facts)
    run = analyse(
        cfg,
        find_settings(cfg),
        gaps_settings(cfg),
        facts,
        digest,
        args.facts.name,
        git_dir=git_dir,
        snapshot_commit=args.snapshot,
        candidates=args.candidates,
    )
    if args.audit:
        run["audit"] = audit_report(run["facts"], read_audit(args.audit))
    if args.sample:
        run["audit_sample"] = audit_template(run["facts"], args.sample, args.seed)
    return run
