import datetime

from shouldercheck.records.checks import stale
from tests.records.conftest import check, rows

BODY = "same text " * 30


def test_identical_files_are_listed_for_every_member(tree):
    root = tree(
        {
            "a.md": BODY,
            "b/copy.md": BODY,
            "c.md": BODY + "x",
            "tiny1.md": "same",
            "tiny2.md": "same",
        }
    )
    report = check(root, '[checks]\ndup-content = "candidate"\n')
    assert [(f.severity, f.path) for f in report.findings] == [
        ("candidate", "a.md"),
        ("candidate", "b/copy.md"),
    ]
    assert report.findings[0].message == "identical to: b/copy.md"
    assert check(root, "").findings == []


def test_stale_reads_the_updated_date_from_front_matter_or_the_head(tree, monkeypatch):
    monkeypatch.setattr(stale, "_today", lambda: datetime.date(2026, 10, 31))
    root = tree(
        {
            "p/old.md": "---\nupdated: 2026-10-10\n---\n",
            "p/head.md": "# H\nstatus: active · updated: 2026-10-15\n",
            "p/fresh.md": "updated: 2026-10-20\n",
            "p/edge.md": "updated: 2026-10-17\n",
            "p/none.md": "no date\n",
            "p/bad.md": "updated: 2026-13-45\n",
            "q/old.md": "updated: 2020-01-01\n",
        }
    )
    toml = '[checks]\nstale = "candidate"\n[stale]\nmatch = ["p/*.md"]\ndays = 14\n'
    report = check(root, toml)
    assert [(f.severity, f.path) for f in report.findings] == [
        ("candidate", "p/head.md"),
        ("candidate", "p/old.md"),
    ]
    assert report.findings[1].message == "updated 2026-10-10 is 21 days old (limit 14)"


def test_stale_needs_a_match_glob(tree, monkeypatch):
    monkeypatch.setattr(stale, "_today", lambda: datetime.date(2026, 10, 31))
    root = tree({"a.md": "updated: 2020-01-01\n"})
    assert rows(check(root, '[checks]\nstale = "candidate"\n'), "stale") == []
