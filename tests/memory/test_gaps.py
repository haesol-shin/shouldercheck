import hashlib
import json
import unicodedata

import pytest

from shouldercheck.cli import main
from shouldercheck.memory.gaps import audit_report, audit_template, coverage
from tests.memory.test_eval import git, history, jsonl

DOCS = {
    "notes/plan.md": (
        "# Launch plan\n\nThe owner approved the two tier question set on Friday.\n\n"
        "Unrelated budget paragraph with receipts.\n"
    ),
    "notes/split.md": "# Split\n\nquestion set draft\n\nthe owner approved nothing here\n",
    "notes/other.md": "# Other\n\ngardening tips\n",
}
CHAT = "### 10:00 · m11\nowner: approved the two tier question set\n"
PROFILE = (
    'include = ["notes/**/*.md"]\n[[find.tiers]]\nname = "transcript"\ninclude = ["chat/*.md"]\n'
)


def fact(ident, keywords, **extra):
    row = {"id": ident, "text": " ".join(keywords), "source": "chat/2026-10-30.md#m11"}
    return {**row, "keywords": keywords, **extra}


def run_gaps(root, facts, *args, capsys):
    path = root / "facts.jsonl"
    path.write_text(jsonl(facts), encoding="utf-8")
    code = main(["gaps", str(path), "--root", str(root), *args])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.startswith("{") else out


def base(tree, extra=None):
    return tree({**DOCS, "chat/2026-10-30.md": CHAT, "shck.toml": PROFILE, **(extra or {})})


def test_present_weak_and_absent(tree, capsys):
    root = base(tree)
    facts = [
        fact("F1", ["owner approved", "two tier", "question set"]),
        fact("F2", ["owner approved", "question set", "friday"]),
        fact("F3", ["wombat", "zeppelin"]),
    ]
    code, data = run_gaps(root, facts, capsys=capsys)
    assert code == 0
    status = {f["id"]: f["status"] for f in data["facts"]}
    assert status == {"F1": "present", "F2": "present", "F3": "absent"}
    assert data["summary"] == {"n": 3, "present": 2, "weak": 0, "absent": 1}
    first = data["facts"][0]["candidates"][0]
    assert first["path"] == "notes/plan.md" and first["coverage"] == 1.0 and first["line"] == 3


def test_keywords_in_different_blocks_are_weak(tree, capsys):
    root = base(tree)
    facts = [
        fact("F1", ["question set", "nothing here", "draft"]),
        fact("F2", ["question set", "budget"]),
    ]
    _, data = run_gaps(root, facts, "--candidates", "10", capsys=capsys)
    rows = {f["id"]: f for f in data["facts"]}
    assert rows["F1"]["status"] == "weak" and rows["F1"]["coverage"] == round(2 / 3, 4)
    assert rows["F2"]["status"] == "weak" and rows["F2"]["coverage"] == 0.5


def test_the_source_file_and_the_transcript_tier_never_count(tree, capsys):
    root = tree(
        {
            **DOCS,
            "notes/src.md": "alpha beta gamma\n",
            "chat/2026-10-30.md": CHAT,
            "shck.toml": PROFILE,
        }
    )
    own = fact("F1", ["alpha", "beta", "gamma"], source="notes/src.md#top")
    chat = fact("F2", ["approved", "tier", "owner:"], source="elsewhere.md")
    _, data = run_gaps(root, [own, chat], capsys=capsys)
    status = {f["id"]: f["status"] for f in data["facts"]}
    assert status["F1"] == "absent"
    assert all(not c["path"].startswith("chat/") for f in data["facts"] for c in f["candidates"])


def test_expect_must_be_among_the_candidates_for_present(tree, capsys):
    root = base(tree)
    keywords = ["owner approved", "two tier", "question set"]
    _, data = run_gaps(
        root,
        [fact("F1", keywords, expect="notes/other.md"), fact("F2", keywords, expect="notes/p*.md")],
        capsys=capsys,
    )
    rows = {f["id"]: f for f in data["facts"]}
    assert rows["F1"]["status"] == "weak" and rows["F1"]["expect_missing"] is True
    assert rows["F2"]["status"] == "present" and "expect_missing" not in rows["F2"]


def test_thresholds_are_profile_keys(tree, capsys):
    keywords = ["owner approved", "question set", "budget", "wombat"]
    root = base(tree)
    _, data = run_gaps(root, [fact("F1", keywords)], capsys=capsys)
    assert data["facts"][0]["status"] == "weak"
    root = base(tree, {"shck.toml": PROFILE + "[gaps]\npresent = 0.5\n"})
    _, data = run_gaps(root, [fact("F1", keywords)], capsys=capsys)
    assert data["facts"][0]["status"] == "present" and data["thresholds"]["present"] == 0.5


def test_coverage_folds_case_and_unicode_form():
    text = "첫 단락\n\nLaunch 논문 Checklist\nsecond line\n\n끝"
    decomposed = unicodedata.normalize("NFD", "논문")
    assert decomposed != "논문"
    share, line, whole = coverage(text, ["launch", decomposed, "checklist"])
    assert (share, line, whole) == (1.0, 3, True)
    assert coverage(text, ["launch", "끝"]) == (0.5, 3, True)
    assert coverage("", ["x"]) == (0.0, 1, False)


def test_snapshot_run_reads_the_commit_not_the_live_tree(tree, tmp_path, capsys):
    repo, commit = history(tmp_path, DOCS)
    live = {"notes/other.md": "# Other\n\ngardening\n", "shck.toml": PROFILE}
    root = tree(live)
    facts = [fact("F1", ["owner approved", "two tier", "question set"])]
    _, data = run_gaps(root, facts, capsys=capsys)
    assert data["facts"][0]["status"] == "absent"
    _, data = run_gaps(
        root, facts, "--snapshot", commit, "--git-dir", str(repo / ".git"), capsys=capsys
    )
    assert data["facts"][0]["status"] == "present" and data["trees"][0]["commit"] == commit
    assert git(repo, "status", "--porcelain") == ""


def test_audit_sample_is_ordered_by_seeded_hash(tree, capsys):
    root = base(tree)
    facts = [fact(f"F{i}", ["wombat"]) for i in range(6)]
    _, first = run_gaps(root, facts, "--sample", "3", "--seed", "20261101", capsys=capsys)
    _, again = run_gaps(root, facts, "--sample", "3", "--seed", "20261101", capsys=capsys)
    _, other = run_gaps(root, facts, "--sample", "3", "--seed", "7", capsys=capsys)
    expected = sorted(
        (f"F{i}" for i in range(6)),
        key=lambda i: hashlib.sha256(f"20261101:{i}".encode()).hexdigest(),
    )
    assert [r["id"] for r in first["audit_sample"]] == expected[:3]
    assert first["audit_sample"] == again["audit_sample"] != other["audit_sample"]
    assert first["audit_sample"][0] == {
        "id": expected[0],
        "shck": "absent",
        "owner": None,
        "note": "",
    }


def test_audit_reports_agreement_and_extractor_precision():
    rows = [{"id": f"F{i}", "status": "present" if i < 6 else "absent"} for i in range(10)]
    owner = ["present"] * 5 + ["weak", "absent", "absent", "invalid-fact", "invalid-fact"]
    audits = [{"id": f"F{i}", "owner": o} for i, o in enumerate(owner)] + [
        {"id": "Z9", "owner": "present"}
    ]
    report = audit_report(rows, audits)
    assert report["audited"] == 10 and report["unknown_ids"] == 1
    assert (report["agreement"]["hits"], report["agreement"]["n"]) == (7, 8)
    assert (report["extractor_precision"]["hits"], report["extractor_precision"]["n"]) == (8, 10)
    assert audit_template(rows, 0, "s") == []


def test_audit_file_through_the_cli(tree, capsys):
    root = base(tree)
    (root / "audits.jsonl").write_text(jsonl([{"id": "F1", "owner": "present"}]), encoding="utf-8")
    _, data = run_gaps(
        root,
        [fact("F1", ["owner approved", "question set"])],
        "--audit",
        str(root / "audits.jsonl"),
        capsys=capsys,
    )
    assert data["audit"]["agreement"]["hits"] == 1


@pytest.mark.parametrize(
    "row",
    [
        {"id": "F", "text": "t", "source": "s", "keywords": []},
        {"id": "F", "text": "t", "source": "s"},
        {"id": "F", "text": "t", "source": "s", "keywords": ["k"], "kind": "gossip"},
        {"id": "F", "text": "t", "source": "s", "keywords": ["k"], "quote": "x" * 201},
        {"text": "t", "source": "s", "keywords": ["k"]},
    ],
)
def test_bad_facts_exit_3(tree, row, capsys):
    root = base(tree)
    (root / "f.jsonl").write_text(jsonl([row]), encoding="utf-8")
    assert main(["gaps", str(root / "f.jsonl"), "--root", str(root)]) == 3
    assert "shck:" in capsys.readouterr().err


def test_usage_errors_and_a_missing_file(tree, capsys):
    root = base(tree)
    (root / "f.jsonl").write_text(jsonl([fact("F1", ["a"])]), encoding="utf-8")
    assert main(["gaps", str(root / "f.jsonl"), "--root", str(root), "--sample", "0"]) == 2
    assert main(["gaps", str(root / "nope.jsonl"), "--root", str(root)]) == 3
    assert (
        main(["gaps", str(root / "f.jsonl"), "--root", str(root), "--live", "--snapshot", "x"]) == 2
    )


def test_gaps_text_format_and_no_writes(tree, state_home, capsys):
    root = base(tree)
    (root / "f.jsonl").write_text(jsonl([fact("F1", ["wombat"])]), encoding="utf-8")
    assert main(["gaps", str(root / "f.jsonl"), "--root", str(root), "--format", "text"]) == 0
    assert "absent  0.00 F1" in capsys.readouterr().out and not state_home.exists()
