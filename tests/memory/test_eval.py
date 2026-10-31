import json
import subprocess

import pytest

from shouldercheck.cli import main
from shouldercheck.memory import evalrun

DOCS = {
    "n/alpha.md": "# Alpha launch\n\nrelease checklist for the launch\n",
    "n/beta.md": "# Beta\n\nlaunch retrospective notes\n",
    "n/gamma.md": "# Gamma\n\nunrelated gardening\n",
    "n/delta.md": "# Delta\n\nfinance receipts\n",
}
PROFILE = '[eval]\ndir = "cases"\ngit_dir = "../repo/.git"\n'


def jsonl(rows):
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def probe(ident, query, expect, **extra):
    return {"id": ident, "query": query, "expect": expect, "writer": "m", **extra}


def run(root, *args, capsys=None):
    code = main(["eval", "--root", str(root), *args])
    out = capsys.readouterr().out if capsys else ""
    return code, (json.loads(out) if out.startswith("{") else out)


def base(tree, rows, name="probes.jsonl", profile=PROFILE, docs=None):
    return tree({**(docs or DOCS), f"cases/{name}": jsonl(rows), "shck.toml": profile})


def test_hit_at_k_mrr_and_per_case_rows(tree, capsys):
    root = base(
        tree,
        [
            probe("P1", "release checklist", "n/alpha.md", source_path="n/alpha.md"),
            probe("P2", "retrospective", "n/beta.md", source_path="n/beta.md"),
            probe("P3", "gardening", "n/delta.md", source_path="n/delta.md"),
        ],
    )
    code, data = run(root, "--set", "probes", capsys=capsys)
    assert code == 0
    hits = data["metrics"]["hit_at"]
    assert (hits["1"]["hits"], hits["3"]["hits"], hits["10"]["hits"], hits["3"]["n"]) == (
        2,
        2,
        2,
        3,
    )
    assert data["metrics"]["mrr"] == round(2 / 3, 4)
    ranks = {c["id"]: c["rank"] for c in data["cases"]}
    assert ranks == {"P1": 1, "P2": 1, "P3": 0}
    assert data["set"]["version"].startswith("probes@") and data["finder"]["config_hash"]
    assert hits["3"]["wilson"][0] < 2 / 3 < hits["3"]["wilson"][1]


def test_overlap_buckets_split_hits_by_shared_vocabulary(tree, capsys):
    root = base(
        tree,
        [
            probe("P1", "alpha launch", "n/alpha.md", source_path="n/alpha.md"),
            probe("P2", "release checklist", "n/alpha.md", source_path="n/alpha.md"),
            probe("P3", "retrospective beta quarterly", "n/beta.md", source_path="n/beta.md"),
        ],
    )
    _, data = run(root, "--set", "probes", capsys=capsys)
    buckets = data["metrics"]["overlap_hit_at_k"]
    assert (buckets["0"]["n"], buckets["under_0.34"]["n"], buckets["0.34_or_more"]["n"]) == (
        1,
        1,
        1,
    )
    assert buckets["0"]["hits"] == 1 and buckets["under_0.34"]["hits"] == 1


def test_abstention_prints_the_score_distribution_until_a_threshold_is_set(tree, capsys):
    rows = [probe("A1", "launch", "none", abstain=True), probe("A2", "zzz nothing", "none")]
    root = base(tree, rows)
    _, data = run(root, "--set", "probes", capsys=capsys)
    absent = data["metrics"]["abstention"]
    assert (
        absent["abstained"] is None
        and absent["top_scores"][0] == 0.0
        and len(absent["top_scores"]) == 2
    )
    assert data["metrics"]["scored"] == 0 and data["metrics"]["hit_at"]["3"]["n"] == 0
    _, data = run(root, "--set", "probes", "--abstain-below", "0.5", capsys=capsys)
    assert data["metrics"]["abstention"]["abstained"]["hits"] == 1


def test_a_gold_path_must_exist_and_contain_the_string(tree, capsys):
    rows = [
        {
            **probe("L1", "launch", "n/alpha.md"),
            "first_failing_stage": "retrieve",
            "must_contain": "checklist",
        },
        {
            **probe("L2", "launch", "n/alpha.md"),
            "first_failing_stage": "retrieve",
            "must_contain": "absent",
        },
        {**probe("L3", "launch", "n/gone.md"), "first_failing_stage": "retrieve"},
    ]
    root = base(tree, rows, name="ledger.jsonl")
    _, data = run(root, "--set", "ledger", "--live", capsys=capsys)
    assert {i["id"] for i in data["invalid"]} == {"L2", "L3"}
    assert data["metrics"]["scored"] == 1


def test_baseline_lists_newly_lost_and_won(tree, capsys, tmp_path):
    rows = [
        probe("P1", "release checklist", "n/alpha.md"),
        probe("P2", "retrospective", "n/beta.md"),
    ]
    root = base(tree, rows)
    _, current = run(root, "--set", "probes", capsys=capsys)
    old = json.loads(json.dumps(current))
    for case in old["cases"]:
        case["rank"] = 0 if case["id"] == "P1" else 5
    old["cases"][1]["rank"] = 1
    path = tmp_path / "base.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    _, data = run(root, "--set", "probes", "--baseline", str(path), capsys=capsys)
    assert data["vs_baseline"]["newly_won"] == ["P1"] and data["vs_baseline"]["newly_lost"] == []
    path.write_text(json.dumps({**old, "cases": [{**c, "rank": 1} for c in old["cases"]]}))
    root2 = base(
        tree, [probe("P1", "zzz", "n/alpha.md"), probe("P2", "retrospective", "n/beta.md")]
    )
    _, data = run(root2, "--set", "probes", "--baseline", str(path), capsys=capsys)
    assert data["vs_baseline"]["newly_lost"] == ["P1"]


def test_gate_exit_codes(tree, capsys):
    good = {**probe("L1", "release checklist", "n/alpha.md"), "first_failing_stage": "retrieve"}
    bad = {**probe("L2", "gardening", "n/delta.md"), "first_failing_stage": "retrieve"}
    root = base(tree, [{**good, "must_pass": True}, bad], name="ledger.jsonl")
    code, data = run(root, "--set", "ledger", "--live", "--gate", capsys=capsys)
    assert code == 0 and data["gate"]["checked"] == 1 and data["gate"]["passed"]
    assert "skipped" in data["gate"]["note"]
    root = base(tree, [good, {**bad, "must_pass": True}], name="ledger.jsonl")
    code, data = run(root, "--set", "ledger", "--live", "--gate", capsys=capsys)
    assert code == 1 and data["gate"]["failed"][0]["id"] == "L2"


def test_gate_fails_when_the_labelled_irrelevant_median_rises(tree, capsys, tmp_path):
    labels = {"n/beta.md": "irrelevant", "n/alpha.md": "relevant"}
    rows = [probe("P1", "launch", "n/alpha.md", labels=labels)]
    root = base(tree, rows)
    _, first = run(root, "--set", "probes", capsys=capsys)
    assert first["metrics"]["irrelevant"]["median_top3"] == 1.0
    older = json.loads(json.dumps(first))
    older["metrics"]["irrelevant"]["median_top3"] = 0.0
    path = tmp_path / "base.json"
    path.write_text(json.dumps(older), encoding="utf-8")
    code, data = run(root, "--set", "probes", "--gate", "--baseline", str(path), capsys=capsys)
    assert code == 1 and "rose" in data["gate"]["failed"][0]["reason"]
    _, plain = run(
        base(tree, [probe("P1", "launch", "n/alpha.md")]), "--set", "probes", capsys=capsys
    )
    assert plain["metrics"]["irrelevant"]["share"] is None
    assert plain["metrics"]["irrelevant"]["reason"] == "no labels"


def git(repo, *args):
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(repo), *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def history(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    return repo, git(repo, "rev-parse", "HEAD")


def test_a_ledger_case_runs_on_its_own_snapshot(tree, tmp_path, capsys):
    repo, commit = history(tmp_path, DOCS)
    live = {k: v for k, v in DOCS.items() if k != "n/alpha.md"}
    rows = [
        {
            **probe("L1", "release checklist", "n/alpha.md"),
            "snapshot": commit,
            "first_failing_stage": "retrieve",
            "must_pass": True,
        },
    ]
    root = tree(
        {
            **live,
            "cases/ledger.jsonl": jsonl(rows),
            "shck.toml": PROFILE.replace("../repo", "../repo"),
        }
    )
    # The profile's git_dir is relative to the profile; point it at the temp repository.
    (root / "shck.toml").write_text(f'[eval]\ndir = "cases"\ngit_dir = "{repo / ".git"}"\n')
    code, data = run(root, "--set", "ledger", "--gate", capsys=capsys)
    assert code == 0 and data["cases"][0]["rank"] == 1 and data["cases"][0]["snapshot"] == commit
    assert data["trees"][0]["docs"] == 4
    code, data = run(root, "--set", "ledger", "--live", "--gate", capsys=capsys)
    assert code == 1 and data["invalid"][0]["reason"].startswith("expected path")
    # A second run reuses the cache keyed by tree hash and still finds the record.
    code, data = run(root, "--set", "ledger", "--gate", capsys=capsys)
    assert code == 0 and data["trees"][0]["tree"] == git(repo, "rev-parse", "HEAD^{tree}")


def test_a_missing_snapshot_or_git_dir_is_reported(tree, tmp_path, capsys):
    repo, _ = history(tmp_path, DOCS)
    rows = [
        {
            **probe("L1", "launch", "n/alpha.md"),
            "snapshot": "deadbeef",
            "first_failing_stage": "retrieve",
        }
    ]
    root = tree({**DOCS, "cases/ledger.jsonl": jsonl(rows), "shck.toml": '[eval]\ndir = "cases"\n'})
    assert main(["eval", "--root", str(root), "--set", "ledger"]) == 2
    assert "git-dir" in capsys.readouterr().err
    assert (
        main(["eval", "--root", str(root), "--set", "ledger", "--git-dir", str(repo / ".git")]) == 3
    )
    assert "deadbeef" in capsys.readouterr().err


@pytest.mark.parametrize(
    "text",
    [
        "not json\n",
        '{"id": "x", "query": "q"}\n',
        '{"id": "x", "query": "q", "expect": "a.md", "first_failing_stage": "nope"}\n',
        '{"id": "x", "query": "q", "expect": "a.md"}\n' * 2,
        '{"id": "x", "query": "q", "expect": "a.md", "labels": {"a.md": "maybe"}}\n',
    ],
)
def test_bad_case_files_exit_3(tree, text, capsys):
    root = tree({"a.md": "x\n", "cases/probes.jsonl": text, "shck.toml": '[eval]\ndir = "cases"\n'})
    assert main(["eval", "--root", str(root), "--set", "probes"]) == 3
    assert "shck:" in capsys.readouterr().err


def test_a_frozen_set_that_changed_is_flagged(tree, capsys):
    rows = [probe("P1", "launch", "n/alpha.md")]
    root = base(tree, rows)
    freeze = root / "cases/probes.freeze.json"
    freeze.write_text(json.dumps({"sha256": "0" * 64, "count": 1}), encoding="utf-8")
    _, data = run(root, "--set", "probes", capsys=capsys)
    assert data["set"]["freeze"] == {"file": "probes.freeze.json", "match": False, "count": 1}


def test_eval_writes_nothing_and_logs_nothing(tree, state_home, capsys):
    root = base(tree, [probe("P1", "launch", "n/alpha.md")])
    before = sorted(str(p) for p in root.rglob("*"))
    run(root, "--set", "probes", capsys=capsys)
    assert sorted(str(p) for p in root.rglob("*")) == before and not state_home.exists()


def make_run(pairs):
    return {
        "set": {"version": "v"},
        "cases": [{"id": i, "set": "probes", "rank": r} for i, r in pairs],
    }


def test_compare_pairs_cases_and_applies_the_exact_test(tmp_path, capsys):
    first = make_run([(f"P{i}", 1) for i in range(20)])
    second = make_run([(f"P{i}", 0 if i < 15 else (1 if i < 18 else 0)) for i in range(20)])
    # Cases 0-14 and 18-19 are lost; 15-17 are kept.
    result = evalrun.compare_runs(first, second, 3)
    assert (result["only_first_hit"], result["only_second_hit"]) == (17, 0)
    assert result["p"] == round(2 / 2**17, 4) and "first run is better" in result["verdict"]
    assert result["per_case_losses"] == sorted(f"P{i}" for i in [*range(15), 18, 19])
    paths = []
    for name, data in (("a", first), ("b", second)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        paths.append(str(path))
    assert main(["eval", "compare", *paths]) == 0
    out = capsys.readouterr().out
    assert "first run is better" in out and not out.startswith("{")
    assert main(["eval", "compare", *paths, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["only_first_hit"] == 17


def test_compare_says_no_detectable_change_for_a_small_gap():
    first = make_run([("P1", 1), ("P2", 1), ("P3", 1), ("P4", 0)])
    second = make_run([("P1", 0), ("P2", 1), ("P3", 1), ("P4", 1)])
    result = evalrun.compare_runs(first, second, 3)
    assert (result["only_first_hit"], result["only_second_hit"], result["p"]) == (1, 1, 1.0)
    assert result["verdict"] == "no detectable change"


def test_compare_never_tests_the_ledger():
    ledger = {"cases": [{"id": "L1", "set": "ledger", "rank": 1}]}
    worse = {"cases": [{"id": "L1", "set": "ledger", "rank": 0}]}
    result = evalrun.compare_runs(ledger, worse, 3)
    assert result["p"] is None and result["verdict"].startswith("not tested")
    assert result["per_case_losses"] == ["L1"]


def test_compare_usage_errors(tree, capsys):
    assert main(["eval", "compare", "only-one.json"]) == 2
    assert "usage" in capsys.readouterr().err
    assert main(["eval", "compare", "a.json", "b.json"]) == 2
