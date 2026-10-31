"""Command-line glue for `shck eval`: resolve the case file, the baseline and the snapshot."""

import argparse
import json
from pathlib import Path

from shouldercheck.memory.cases import CaseSet, read_cases
from shouldercheck.memory.evalrun import compare_runs, run_eval
from shouldercheck.memory.settings import eval_settings, find_settings, resolve_dir
from shouldercheck.records.config import Config, ConfigError

KEYWORDS = ("ledger", "probes")


def case_file(cfg: Config, name: str) -> tuple[Path, str | None]:
    """`ledger` and `probes` live in the profile's eval folder; anything else is a path."""
    if name not in KEYWORDS:
        return Path(name), None
    options = eval_settings(cfg)
    if options.dir is None:
        raise ConfigError(f"--set {name} needs [eval] dir in the profile")
    return resolve_dir(options.dir, cfg, cfg.root) / f"{name}.jsonl", name


def load_run(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "cases" not in data:
            raise ValueError("not an eval run")
        return data
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot use run file {path.name}: {exc}") from exc


def read_set(cfg: Config, name: str) -> CaseSet:
    path, kind = case_file(cfg, name)
    return read_cases(path, kind)


def run_eval_command(cfg: Config, args: argparse.Namespace) -> dict:
    options = eval_settings(cfg)
    if args.operands:
        if args.operands[0] != "compare" or len(args.operands) != 3:
            raise ConfigError("usage: shck eval compare A.json B.json")
        first, second = (load_run(Path(p)) for p in args.operands[1:])
        return compare_runs(first, second, args.k)
    if args.live and args.snapshot:
        raise ConfigError("--live and --snapshot cannot be combined")
    git_dir = args.git_dir or (
        resolve_dir(options.git_dir, cfg, cfg.root) if options.git_dir else None
    )
    baseline = load_run(args.baseline) if args.baseline else None
    below = args.abstain_below if args.abstain_below is not None else options.abstain_below
    return run_eval(
        cfg,
        find_settings(cfg),
        options,
        read_set(cfg, args.case_set),
        git_dir=git_dir,
        snapshot_commit=args.snapshot,
        live=args.live,
        k=args.k,
        baseline=baseline,
        abstain_below=below,
        gate=args.gate,
    )


def render_compare_text(result: dict) -> str:
    first, second = result["set_versions"]
    lines = [
        f"compare at k={result['k']}: {result['paired']} paired probe cases ({first} vs {second})",
        f"only the first run hit: {result['only_first_hit']}, only the second: "
        f"{result['only_second_hit']}, p = {result['p']}",
        result["verdict"],
    ]
    if result["per_case_losses"]:
        lines.append("lost: " + ", ".join(result["per_case_losses"]))
    if result["per_case_wins"]:
        lines.append("won: " + ", ".join(result["per_case_wins"]))
    return "\n".join(lines) + "\n"
