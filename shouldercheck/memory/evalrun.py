"""`shck eval`: run case files through the finder and measure where the expected record lands."""

from pathlib import Path

from shouldercheck import __version__
from shouldercheck.memory.cases import Case, CaseSet, freeze_state
from shouldercheck.memory.find import Index, rank_records
from shouldercheck.memory.settings import (
    RECORDS,
    EvalSettings,
    FindSettings,
)
from shouldercheck.memory.stats import mcnemar_exact, median, wilson
from shouldercheck.memory.store import config_hash
from shouldercheck.memory.tokens import tokenize
from shouldercheck.memory.trees import Trees
from shouldercheck.records.config import Config

SCHEMA_VERSION = 1
GATE_K = 3
ALPHA = 0.05
BUCKETS = ("0", "under_0.34", "0.34_or_more")


def _paths(index: Index) -> dict[str, int]:
    return {d.path: d.id for d in index.store.docs().values() if d.tier == RECORDS}


def _invalid(case: Case, commit: str | None, paths: dict[str, int], trees: Trees) -> str | None:
    if case.expect is None:
        return None
    if case.expect not in paths:
        return "expected path is not in the searched tree"
    if case.must_contain is not None:
        text = trees.read(commit, case.expect)
        if text is None or case.must_contain not in text:
            return "expected file does not contain must_contain"
    return None


def _overlap(index: Index, case: Case) -> float | None:
    """Share of query tokens found in the source document's title, alias and name tokens."""
    docs = {d.path: d for d in index.store.docs().values() if d.tier == RECORDS}
    source = docs.get(case.source_path or "")
    query = set(tokenize(case.query))
    if source is None or not query:
        return None
    stem = source.path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
    names = tokenize(" ".join([source.title, *index.store.aliases_of(source.id), stem]))
    return len(query & set(names)) / len(query)


def _bucket(share: float) -> str:
    return BUCKETS[0] if share == 0 else BUCKETS[1] if share < 0.34 else BUCKETS[2]


def _share(hits: int, total: int) -> dict:
    low, high = wilson(hits, total)
    return {
        "hits": hits,
        "n": total,
        "share": round(hits / total, 4) if total else None,
        "wilson": [round(low, 4), round(high, 4)],
    }


def run_eval(
    cfg: Config,
    find: FindSettings,
    options: EvalSettings,
    case_set: CaseSet,
    *,
    git_dir: Path | None,
    snapshot_commit: str | None,
    live: bool,
    k: int,
    baseline: dict | None,
    abstain_below: float | None,
    gate: bool,
) -> dict:
    trees = Trees(cfg, find, git_dir)
    rows: list[dict] = []
    buckets: dict[str, list[int]] = {name: [0, 0] for name in BUCKETS}
    irrelevant_counts: list[int] = []
    labelled_pairs = {"labelled": 0, "irrelevant": 0, "on_topic_wrong": 0}
    try:
        for case in case_set.cases:
            commit = None if live else (snapshot_commit or case.snapshot)
            index, key = trees.open(commit)
            ranked = rank_records(index, case.query)
            reason = _invalid(case, commit, _paths(index), trees)
            order = [r.doc.path for r in ranked]
            rank = 0
            if case.expect in order[: options.rank_cap]:
                rank = order.index(case.expect) + 1
            row = {
                "id": case.id,
                "set": case.set,
                "abstain": case.abstain,
                "rank": rank,
                "top_path": order[0] if order else None,
                "top_score": round(ranked[0].score, 4) if ranked else 0.0,
                "must_pass": case.must_pass,
                "stage": case.stage,
                "tree": key,
                "snapshot": commit,
            }
            if reason:
                row["invalid"] = reason
            elif case.expect is not None:
                share = _overlap(index, case)
                if share is not None:
                    bucket = buckets[_bucket(share)]
                    bucket[0] += 1
                    bucket[1] += int(0 < rank <= k)
                    row["overlap"] = round(share, 4)
            if not reason and case.labels:
                counted = _label_counts(case, order[:k], labelled_pairs)
                irrelevant_counts.append(counted)
                row["irrelevant_top_k"] = counted
            rows.append(row)
        tree_info = trees.info()
    finally:
        trees.close()
    return _assemble(
        cfg,
        case_set,
        rows,
        tree_info,
        options,
        k,
        abstain_below,
        buckets,
        irrelevant_counts,
        labelled_pairs,
        baseline,
        gate,
    )


def _label_counts(case: Case, top: list[str], pairs: dict[str, int]) -> int:
    irrelevant = 0
    for path in top:
        label = case.labels.get(path)
        if label is None:
            continue
        pairs["labelled"] += 1
        irrelevant += label == "irrelevant"
        pairs["irrelevant"] += label == "irrelevant"
        pairs["on_topic_wrong"] += label == "on-topic-wrong"
    return irrelevant


def _hit(rank: int, k: int) -> bool:
    return 0 < rank <= k


def _assemble(
    cfg: Config,
    case_set: CaseSet,
    rows: list[dict],
    tree_info: list[dict],
    options: EvalSettings,
    k: int,
    abstain_below: float | None,
    buckets: dict[str, list[int]],
    irrelevant_counts: list[int],
    pairs: dict[str, int],
    baseline: dict | None,
    gate: bool,
) -> dict:
    scored = [r for r in rows if not r["abstain"] and "invalid" not in r]
    metrics = {
        "scored": len(scored),
        "hit_at": {
            str(n): _share(sum(_hit(r["rank"], n) for r in scored), len(scored))
            for n in sorted({*options.k, k})
        },
        "mrr": round(sum(1 / r["rank"] for r in scored if r["rank"]) / len(scored), 4)
        if scored
        else None,
        "overlap_hit_at_k": {name: _share(v[1], v[0]) for name, v in buckets.items()},
        "abstention": _abstention(rows, abstain_below),
        "irrelevant": _irrelevant(pairs, irrelevant_counts, k),
    }
    run = {
        "schema_version": SCHEMA_VERSION,
        "kind": "eval",
        "finder": {"shck": __version__, "config_hash": config_hash(cfg)},
        "set": {
            "name": case_set.name,
            "file": case_set.path.name,
            "version": case_set.version,
            "cases": len(case_set.cases),
            "freeze": freeze_state(case_set),
        },
        "trees": tree_info,
        "k": k,
        "rank_cap": options.rank_cap,
        "metrics": metrics,
        "invalid": [{"id": r["id"], "reason": r["invalid"]} for r in rows if "invalid" in r],
        "cases": rows,
    }
    if baseline is not None:
        run["vs_baseline"] = _against(rows, baseline, k)
    if gate:
        run["gate"] = _gate(rows, metrics, baseline)
    return run


def _abstention(rows: list[dict], below: float | None) -> dict:
    scores = sorted(r["top_score"] for r in rows if r["abstain"] and "invalid" not in r)
    out: dict = {"n": len(scores), "top_scores": scores, "abstain_below": below}
    if below is None:
        out |= {"abstained": None, "reason": "no abstain_below; choose it from top_scores"}
    else:
        out |= {"abstained": _share(sum(s < below for s in scores), len(scores))}
    return out


def _irrelevant(pairs: dict[str, int], counts: list[int], k: int) -> dict:
    if not pairs["labelled"]:
        return {"k": k, "share": None, "median_top3": None, "reason": "no labels"}
    return {
        "k": k,
        **pairs,
        "share": round(pairs["irrelevant"] / pairs["labelled"], 4),
        "median_top3": median([float(c) for c in counts]),
    }


def _against(rows: list[dict], baseline: dict, k: int) -> dict:
    before = {r["id"]: _hit(r["rank"], k) for r in baseline.get("cases", []) if "invalid" not in r}
    lost, won = [], []
    for row in rows:
        if "invalid" in row or row["id"] not in before or row["abstain"]:
            continue
        now = _hit(row["rank"], k)
        if before[row["id"]] and not now:
            lost.append(row["id"])
        elif now and not before[row["id"]]:
            won.append(row["id"])
    return {
        "set_version": baseline.get("set", {}).get("version"),
        "newly_lost": lost,
        "newly_won": won,
    }


def _gate(rows: list[dict], metrics: dict, baseline: dict | None) -> dict:
    """A must_pass case fails the gate when the record is outside the top three, and also when
    its gold is invalid: a case that cannot be checked protects nothing."""
    pinned = [r for r in rows if r["must_pass"] and not r["abstain"]]
    failed = []
    for r in pinned:
        if "invalid" in r:
            failed.append({"id": r["id"], "rank": r["rank"], "reason": r["invalid"]})
        elif not _hit(r["rank"], GATE_K):
            reason = f"expected record not in top {GATE_K}"
            failed.append({"id": r["id"], "rank": r["rank"], "reason": reason})
    checked = len(pinned)
    now = metrics["irrelevant"]["median_top3"]
    before = ((baseline or {}).get("metrics", {}).get("irrelevant") or {}).get("median_top3")
    note = None
    if now is None or before is None:
        note = "irrelevant-in-top-3 clause skipped: no labels in this run or the baseline"
    elif now > before:
        failed.append({"id": None, "reason": f"irrelevant median rose from {before} to {now}"})
    return {"checked": checked, "failed": failed, "passed": not failed, "note": note}


def compare_runs(first: dict, second: dict, k: int) -> dict:
    """Pair two runs on case id; exact McNemar over probe cases only."""

    def hits(run: dict) -> dict[str, bool]:
        return {
            r["id"]: _hit(r["rank"], k)
            for r in run.get("cases", [])
            if r.get("set") == "probes" and not r.get("abstain") and "invalid" not in r
        }

    a, b = hits(first), hits(second)
    ids = sorted(set(a) & set(b))
    only_a = [i for i in ids if a[i] and not b[i]]
    only_b = [i for i in ids if b[i] and not a[i]]
    ledger = {
        r["id"]: _hit(r["rank"], k) for r in first.get("cases", []) if r.get("set") == "ledger"
    }
    ledger_b = {
        r["id"]: _hit(r["rank"], k) for r in second.get("cases", []) if r.get("set") == "ledger"
    }
    lost = only_a + [
        i for i in sorted(set(ledger) & set(ledger_b)) if ledger[i] and not ledger_b[i]
    ]
    result: dict = {
        "schema_version": SCHEMA_VERSION,
        "kind": "compare",
        "k": k,
        "set_versions": [first.get("set", {}).get("version"), second.get("set", {}).get("version")],
        "paired": len(ids),
        "only_first_hit": len(only_a),
        "only_second_hit": len(only_b),
        "per_case_losses": lost,
        "per_case_wins": only_b,
    }
    if not ids:
        result |= {
            "p": None,
            "verdict": "not tested: no paired probe cases (tier A is never tested)",
        }
        return result
    p = mcnemar_exact(len(only_a), len(only_b))
    result["p"] = round(p, 4)
    if p >= ALPHA:
        result["verdict"] = "no detectable change"
    else:
        better = "first" if len(only_a) > len(only_b) else "second"
        result["verdict"] = f"{better} run is better (p < {ALPHA})"
    return result


def render_run_text(run: dict) -> str:
    metrics = run["metrics"]
    lines = [
        f"set {run['set']['version']} ({run['set']['cases']} cases), finder {run['finder']['shck']}"
        f" config {run['finder']['config_hash']}"
    ]
    lines += [f"tree {t['tree'][:12]} docs {t['docs']}" for t in run["trees"]]
    for key, value in metrics["hit_at"].items():
        lines.append(
            f"Hit@{key}: {value['hits']} of {value['n']}"
            f" (Wilson {value['wilson'][0]} to {value['wilson'][1]})"
        )
    lines.append(f"MRR (cap {run['rank_cap']}): {metrics['mrr']}")
    for name, value in metrics["overlap_hit_at_k"].items():
        lines.append(f"overlap {name}: {value['hits']} of {value['n']}")
    absent = metrics["abstention"]
    lines.append(f"abstention items {absent['n']}: top scores {absent['top_scores']}")
    lines += [f"invalid {i['id']}: {i['reason']}" for i in run["invalid"]]
    if "vs_baseline" in run:
        lines.append(
            f"newly lost {run['vs_baseline']['newly_lost']}, won {run['vs_baseline']['newly_won']}"
        )
    if "gate" in run:
        gate = run["gate"]
        lines.append(
            f"gate {'passed' if gate['passed'] else 'FAILED'} ({gate['checked']} must_pass cases)"
        )
        lines += [f"  {f['id']}: {f['reason']}" for f in gate["failed"]]
        if gate["note"]:
            lines.append(f"  {gate['note']}")
    return "\n".join(lines) + "\n"
