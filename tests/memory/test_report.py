import gzip
import json

from shouldercheck.cli import main
from tests.memory.test_eval import jsonl, probe

STAGES = ["capture"] * 1 + ["write"] * 2 + ["trigger"] * 3 + ["retrieve"] * 8 + ["use"] * 1
PROFILE = '[eval]\ndir = "cases"\n'


def ledger(stages, dates=None):
    rows = []
    for i, stage in enumerate(stages):
        row = {**probe(f"L{i}", "q", "a.md"), "first_failing_stage": stage}
        rows.append({**row, "date": (dates or {}).get(i, "2026-10-21")})
    return rows


def report(root, *args, capsys):
    code = main(["report", "--root", str(root), "--format", "json", *args])
    out = capsys.readouterr()
    return code, json.loads(out.out) if out.out.startswith("{") else out


def test_funnel_denominators_are_the_cases_that_passed_earlier_stages(tree, capsys):
    root = tree({"a.md": "x\n", "cases/ledger.jsonl": jsonl(ledger(STAGES)), "shck.toml": PROFILE})
    _, data = report(root, capsys=capsys)
    stages = {s["stage"]: s for s in data["funnel"]["stages"]}
    assert [(s, stages[s]["hits"], stages[s]["n"]) for s in stages] == [
        ("capture", 1, 15),
        ("write", 2, 14),
        ("trigger", 3, 12),
        ("retrieve", 8, 9),
        ("use", 1, 1),
    ]
    assert stages["retrieve"]["wilson"] is None  # fewer than ten cases: counts only
    assert stages["capture"]["wilson"] is not None
    assert data["funnel"]["set"].startswith("ledger@")


def test_the_design_example_retrieve_8_of_12(tree, capsys):
    stages = ["retrieve"] * 8 + ["use"] * 4
    root = tree({"cases/ledger.jsonl": jsonl(ledger(stages)), "shck.toml": PROFILE})
    code = main(["report", "--root", str(root)])
    assert code == 0
    assert "retrieve: 8 of 12 (Wilson 0.39 to 0.86)" in capsys.readouterr().out


def test_ambiguous_cases_are_left_out_and_counted(tree, capsys):
    rows = ledger(["retrieve"] * 10)
    rows[0]["ambiguous"] = True
    root = tree({"cases/ledger.jsonl": jsonl(rows), "shck.toml": PROFILE})
    _, data = report(root, capsys=capsys)
    assert data["funnel"]["cases"] == 9 and data["funnel"]["ambiguous"] == 1


def make_eval(hits, n):
    return {
        "kind": "eval",
        "set": {"version": "probes@abc"},
        "finder": {"shck": "0.0.0", "config_hash": "ab12cd34"},
        "trees": [{"tree": "t" * 40, "commit": None, "docs": 5}],
        "metrics": {
            "hit_at": {"3": {"hits": hits, "n": n}},
            "overlap_hit_at_k": {"0": {"hits": 1, "n": 4}, "under_0.34": {"hits": 0, "n": 0}},
        },
        "cases": [],
    }


def make_gaps(present, weak, absent, **extra):
    n = present + weak + absent
    return {
        "kind": "gaps",
        "facts_file": {"file": "f.jsonl", "sha256": "f" * 64, "count": n},
        "finder": {"shck": "0.0.0", "config_hash": "ab12cd34"},
        "trees": [{"tree": "x", "commit": "81434e1", "docs": 3}],
        "summary": {"n": n, "present": present, "weak": weak, "absent": absent},
        "facts": [{"id": f"F{i}", "status": "present"} for i in range(n)],
        **extra,
    }


def test_runs_carry_set_tree_and_finder_and_other_json_is_skipped(tree, capsys):
    root = tree(
        {
            "cases/runs/a.json": json.dumps(make_eval(5, 20)),
            "cases/runs/b.json": json.dumps(make_gaps(6, 2, 2)),
            "cases/runs/c.json": json.dumps({"kind": "compare", "p": 0.04}),
            "cases/runs/notes.json": "[]",
            "shck.toml": PROFILE,
        }
    )
    _, data = report(root, capsys=capsys)
    (hit,) = data["retrieve_hit_at_3"]
    assert (hit["hits"], hit["n"], hit["set"], hit["finder"]["config_hash"]) == (
        5,
        20,
        "probes@abc",
        "ab12cd34",
    )
    assert hit["wilson"] == [0.1119, 0.4687] or round(hit["wilson"][0], 2) == 0.11
    assert hit["overlap"]["0"]["n"] == 4 and hit["overlap"]["0"]["wilson"] is None
    (write,) = data["write_recall"]
    assert (write["hits"], write["n"], write["weak"], write["absent"]) == (6, 10, 2, 2)
    assert write["trees"] == [{"tree": "x", "commit": "81434e1"}]


def test_audit_files_are_paired_with_gaps_runs(tree, capsys):
    audit = jsonl(
        [{"id": f"F{i}", "owner": "present" if i < 8 else "invalid-fact"} for i in range(10)]
    )
    root = tree(
        {
            "cases/runs/b.json": json.dumps(make_gaps(10, 0, 0)),
            "audit.jsonl": audit,
            "shck.toml": PROFILE,
        }
    )
    _, data = report(root, "--audit", str(root / "audit.jsonl"), capsys=capsys)
    (row,) = data["audits"]
    assert (row["agreement"]["hits"], row["agreement"]["n"]) == (8, 8)
    assert (row["extractor_precision"]["hits"], row["extractor_precision"]["n"]) == (8, 10)


def test_trigger_rate_and_unknown_callers_from_the_query_log(tree, state_home, capsys):
    rows = ledger(["retrieve"] * 3, {0: "2026-10-21", 1: "2026-10-22", 2: "2026-10-23"})
    root = tree({"cases/ledger.jsonl": jsonl(rows), "shck.toml": PROFILE})
    assert main(["find", "x", "--root", str(root), "--no-log"]) == 0
    capsys.readouterr()
    folder = state_home / "shck"
    from shouldercheck.memory import qlog
    from shouldercheck.memory.settings import find_settings
    from tests.memory.conftest import load

    cfg = load(root)
    log = qlog.log_dir(cfg, find_settings(cfg))
    log.mkdir(parents=True)
    (log / "2026-10-21.jsonl").write_text(
        '{"query":"a","caller":"omp"}\n{"query":"b","caller":"unknown"}\nnot json\n',
        encoding="utf-8",
    )
    (log / "2026-10-22.jsonl.gz").write_bytes(gzip.compress(b'{"query":"c","caller":"unknown"}\n'))
    _, data = report(root, capsys=capsys)
    assert folder.exists()
    assert data["query_log"]["calls"] == 3 and data["query_log"]["log_days"] == 2
    assert (data["query_log"]["trigger"]["hits"], data["query_log"]["trigger"]["n"]) == (2, 3)
    assert data["query_log"]["unknown_callers"]["hits"] == 2


def test_missing_inputs_say_so_instead_of_failing(tree, capsys):
    root = tree({"a.md": "x\n"})
    code, data = report(root, capsys=capsys)
    assert code == 0 and data["funnel"] is None and data["retrieve_hit_at_3"] == []
    assert data["query_log"]["trigger"] is None and "ledger" in data["query_log"]["reason"]
    assert main(["report", "--root", str(root)]) == 0
    assert "query log: 0 calls" in capsys.readouterr().out


def test_unreadable_run_file_exits_3(tree, capsys):
    root = tree({"runs/bad.json": "{nope", "shck.toml": PROFILE})
    assert main(["report", "--root", str(root), "--runs", str(root / "runs")]) == 3
    assert "bad.json" in capsys.readouterr().err


def test_report_writes_nothing(tree, state_home, capsys):
    root = tree({"cases/ledger.jsonl": jsonl(ledger(["write"] * 11)), "shck.toml": PROFILE})
    before = sorted(str(p) for p in root.rglob("*"))
    main(["report", "--root", str(root)])
    assert sorted(str(p) for p in root.rglob("*")) == before and not state_home.exists()
