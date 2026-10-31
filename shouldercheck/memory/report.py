"""`shck report`: count failures per stage from eval runs, gaps runs, the ledger and the query log.

Every share is a count over a count with a Wilson 95% interval; below ten cases only the counts
print. There is no composite score: stage 4 (use) comes from ledger labels only, because shck has
no model.
"""

import gzip
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from shouldercheck import __version__
from shouldercheck.memory.cases import STAGES, CaseError, CaseSet
from shouldercheck.memory.evalrun import SCHEMA_VERSION
from shouldercheck.memory.gaps import audit_report, read_audit
from shouldercheck.memory.stats import wilson

MIN_N = 10


def share(hits: int, total: int) -> dict:
    """Counts always; the share and interval only from `MIN_N` cases up."""
    row: dict = {"hits": hits, "n": total, "share": None, "wilson": None}
    if total >= MIN_N:
        low, high = wilson(hits, total)
        row["share"] = round(hits / total, 4)
        row["wilson"] = [round(low, 4), round(high, 4)]
    return row


def funnel(case_set: CaseSet | None) -> dict | None:
    """Failures per stage; each stage's denominator is the cases that passed the earlier ones."""
    if case_set is None:
        return None
    cases = [c for c in case_set.cases if not c.ambiguous]
    counts = Counter(c.stage for c in cases)
    remaining = len(cases)
    stages = []
    for stage in STAGES:
        stages.append({"stage": stage, **share(counts[stage], remaining)})
        remaining -= counts[stage]
    return {
        "set": case_set.version,
        "cases": len(cases),
        "ambiguous": len(case_set.cases) - len(cases),
        "stages": stages,
    }


def load_runs(paths: Iterable[Path]) -> list[dict]:
    """Eval and gaps runs from files or folders of `*.json`; other JSON files are skipped."""
    files: list[Path] = []
    for path in paths:
        files += sorted(path.glob("*.json")) if path.is_dir() else [path]
    runs = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CaseError(f"cannot read run file {path.name}: {exc}") from exc
        if isinstance(data, dict) and data.get("kind") in ("eval", "gaps"):
            runs.append({**data, "_file": path.name})
    return runs


def _source(run: dict) -> dict:
    """What every number must carry: the set, the tree and the finder."""
    return {
        "file": run["_file"],
        "set": (run.get("set") or run.get("facts_file") or {}).get("version")
        or (run.get("facts_file") or {}).get("sha256", "")[:12],
        "trees": [{"tree": t["tree"], "commit": t.get("commit")} for t in run.get("trees", [])],
        "finder": run.get("finder"),
    }


def retrieval(runs: list[dict]) -> list[dict]:
    rows = []
    for run in (r for r in runs if r["kind"] == "eval"):
        hit = run["metrics"]["hit_at"].get("3")
        if hit is None:
            continue
        rows.append(
            {
                **_source(run),
                "k": 3,
                **share(hit["hits"], hit["n"]),
                "overlap": {
                    name: share(b["hits"], b["n"])
                    for name, b in run["metrics"]["overlap_hit_at_k"].items()
                },
            }
        )
    return rows


def writing(runs: list[dict]) -> list[dict]:
    rows = []
    for run in (r for r in runs if r["kind"] == "gaps"):
        summary = run["summary"]
        row = {**_source(run), **share(summary["present"], summary["n"])}
        row["weak"], row["absent"] = summary["weak"], summary["absent"]
        if "audit" in run:
            row["audit"] = run["audit"]
        rows.append(row)
    return rows


def audits(runs: list[dict], files: list[Path]) -> list[dict]:
    facts = [row for run in runs if run["kind"] == "gaps" for row in run["facts"]]
    result = []
    for path in files:
        data = audit_report(facts, read_audit(path))
        result.append(
            {
                "file": path.name,
                "audited": data["audited"],
                "unknown_ids": data["unknown_ids"],
                "agreement": share(data["agreement"]["hits"], data["agreement"]["n"]),
                "extractor_precision": share(
                    data["extractor_precision"]["hits"], data["extractor_precision"]["n"]
                ),
            }
        )
    return result


def read_log(folder: Path) -> dict[str, list[dict]]:
    """Logged find calls per UTC day, from `.jsonl` and compressed `.jsonl.gz` day files."""
    days: dict[str, list[dict]] = {}
    if not folder.is_dir():
        return days
    for path in sorted(folder.iterdir()):
        name = path.name
        if name.endswith(".jsonl.gz"):
            day, opener = name.removesuffix(".jsonl.gz"), gzip.open
        elif name.endswith(".jsonl"):
            day, opener = name.removesuffix(".jsonl"), open
        else:
            continue
        try:
            with opener(path, "rt", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except (OSError, EOFError, UnicodeDecodeError):
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and "query" in row:
                days.setdefault(day, []).append(row)
    return days


def trigger(case_set: CaseSet | None, log: dict[str, list[dict]]) -> dict:
    """Ledger cases with a logged `find` on their own day; the share of `unknown` callers."""
    rows = [call for calls in log.values() for call in calls]
    callers = share(sum(r.get("caller") == "unknown" for r in rows), len(rows))
    result: dict = {"log_days": len(log), "calls": len(rows), "unknown_callers": callers}
    dated = [c for c in (case_set.cases if case_set else []) if c.date and not c.ambiguous]
    if not dated or not log:
        result["trigger"] = None
        result["reason"] = "needs a ledger with dates and a query log"
        return result
    result["trigger"] = share(sum(c.date in log for c in dated), len(dated))
    return result


def build(
    case_set: CaseSet | None,
    runs: list[dict],
    audit_files: list[Path],
    log: dict[str, list[dict]],
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "report",
        "shck": __version__,
        "funnel": funnel(case_set),
        "retrieve_hit_at_3": retrieval(runs),
        "write_recall": writing(runs),
        "audits": audits(runs, audit_files),
        "query_log": trigger(case_set, log),
    }


def _fmt(row: dict) -> str:
    text = f"{row['hits']} of {row['n']}"
    if row["wilson"]:
        text += f" (Wilson {row['wilson'][0]:.2f} to {row['wilson'][1]:.2f})"
    return text


def render_text(report: dict) -> str:
    lines = [f"shck {report['shck']}"]
    funnel_data = report["funnel"]
    if funnel_data:
        lines.append(
            f"failure funnel from {funnel_data['set']}: {funnel_data['cases']} cases"
            f" ({funnel_data['ambiguous']} ambiguous left out)"
        )
        lines += [f"  {s['stage']}: {_fmt(s)}" for s in funnel_data["stages"]]
    for row in report["retrieve_hit_at_3"]:
        lines.append(f"retrieve Hit@3 on {row['set']} [{_where(row)}]: {_fmt(row)}")
        lines += [f"  overlap {name}: {_fmt(b)}" for name, b in row["overlap"].items()]
    for row in report["write_recall"]:
        lines.append(
            f"write recall, present in {row['set']} [{_where(row)}]: {_fmt(row)}"
            f", weak {row['weak']}, absent {row['absent']}"
        )
    for row in report["audits"]:
        lines.append(
            f"audit {row['file']}: agreement {_fmt(row['agreement'])}; "
            f"valid extracted facts {_fmt(row['extractor_precision'])}"
        )
    log = report["query_log"]
    lines.append(f"query log: {log['calls']} calls on {log['log_days']} days")
    lines.append(f"  unknown callers: {_fmt(log['unknown_callers'])}")
    lines.append(f"  trigger: {_fmt(log['trigger']) if log['trigger'] else log['reason']}")
    return "\n".join(lines) + "\n"


def _where(row: dict) -> str:
    trees = ", ".join((t["commit"] or "live") for t in row["trees"])
    finder = row.get("finder") or {}
    return f"{trees}; finder {finder.get('shck')} {finder.get('config_hash')}"
