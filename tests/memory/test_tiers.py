import json

import pytest

from shouldercheck.cli import main
from shouldercheck.records.config import ConfigError
from tests.memory.conftest import find, load, paths

TIER = """
[[find.tiers]]
name = "transcript"
include = ["chat/*.md"]
unit = "entry"
entry_pattern = '^### \\d{2}:\\d{2} · m(\\d+)$'
anchor_prefix = "m"
max_hits = 2
"""
PROFILE = 'include = ["notes/**/*.md"]\n' + TIER
CHAT = (
    "# Chat 2026-10-30\n\n> automatic log\n\n"
    "### 10:00 · m11\nowner: please remember the launch checklist\n\n"
    "### 10:05 · m12\nagent: noted, widget launch moved\n\n"
    "### 10:09 · m13\nowner: unrelated lunch\n"
)
FILES = {"notes/a.md": "launch plan\n", "notes/b.md": "widget\n", "chat/2026-10-30.md": CHAT}


def test_entries_come_after_records_with_continuing_ranks(tree):
    result = find(tree(FILES), "launch", PROFILE)
    assert paths(result) == ["notes/a.md"]
    assert {h["path"] for h in result.transcript} == {
        "chat/2026-10-30.md#m11",
        "chat/2026-10-30.md#m12",
    }
    assert [h["rank"] for h in result.hits + result.transcript] == [1, 2, 3]
    assert {h["tier"] for h in result.transcript} == {"transcript"}


def test_a_stronger_transcript_hit_never_outranks_a_record(tree):
    files = FILES | {"chat/2026-10-31.md": "### 11:00 · m20\n" + "launch " * 50 + "\n"}
    result = find(tree(files), "launch", PROFILE)
    assert paths(result) == ["notes/a.md"]
    assert result.transcript[0]["score"] > result.hits[0]["score"]


def test_transcript_statistics_do_not_move_record_scores(tree):
    plain = find(tree({"notes/a.md": "launch plan\n", "notes/b.md": "widget\n"}), "launch", PROFILE)
    with_chat = find(tree(FILES), "launch", PROFILE)
    assert plain.hits[0]["score"] == with_chat.hits[0]["score"]


def test_max_hits_and_scope(tree):
    root = tree(FILES)
    assert len(find(root, "launch", PROFILE).transcript) == 2
    records = find(root, "launch", PROFILE, scope="records")
    assert paths(records) == ["notes/a.md"] and records.transcript == []
    only = find(root, "launch", PROFILE, scope="transcript")
    assert only.hits == [] and len(only.transcript) == 2


def test_hit_has_a_masked_entry_snippet_not_the_whole_file(tree):
    secret = "to" + "ken=" + "hunter2" * 2
    chat = "### 10:00 · m11\nlaunch " + secret + "\n\n### 10:01 · m12\nother\n"
    hit = find(tree({"chat/x.md": chat}), "launch", PROFILE).transcript[0]
    assert "hunter2" not in json.dumps(hit) and "other" not in hit["snippet"]


def test_text_before_the_first_header_is_searchable_and_file_unit_works(tree):
    root = tree({"chat/x.md": "preamble about zebra\n### 10:00 · m1\nbody\n"})
    assert find(root, "zebra", PROFILE).transcript[0]["path"] == "chat/x.md"
    whole = PROFILE.replace('unit = "entry"', 'unit = "file"')
    assert find(root, "body", whole).transcript[0]["path"] == "chat/x.md"


def test_a_file_in_the_record_scope_stays_a_record(tree):
    root = tree({"chat/x.md": "### 10:00 · m1\nlaunch\n"})
    result = find(root, "launch", 'include = ["**/*.md"]\n' + TIER)
    assert paths(result) == ["chat/x.md"] and result.transcript == []


def test_tier_files_are_outside_the_check_scope(tree, capsys):
    root = tree(FILES | {"shck.toml": PROFILE})
    assert main(["check", "--root", str(root), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["scan"]["files"] == 2


def test_an_edited_chat_file_replaces_its_entries(tree):
    root = tree(FILES)
    find(root, "launch", PROFILE)
    (root / "chat/2026-10-30.md").write_text(
        CHAT + "\n### 10:30 · m14\nlaunch again\n" * 3, "utf-8"
    )
    result = find(root, "launch", PROFILE)
    assert result.index.state == "incremental"
    assert any(h["path"].endswith("#m14") for h in result.transcript)


def test_a_source_file_can_be_left_out(tree):
    result = find(tree(FILES), "launch", PROFILE, skip_files={"chat/2026-10-30.md"})
    assert result.transcript == []


def test_text_output_marks_the_low_rank_block(tree, capsys):
    root = tree(FILES | {"shck.toml": PROFILE})
    assert main(["find", "launch", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert out.index("1. notes/a.md") < out.index("transcript (low rank") < out.index("#m11")


@pytest.mark.parametrize(
    "toml",
    [
        '[[find.tiers]]\nname = "records"\ninclude = ["a/*.md"]\n',
        '[[find.tiers]]\nname = "t"\n',
        '[[find.tiers]]\nname = "t"\ninclude = ["a/*.md"]\nunit = "entry"\n',
        '[[find.tiers]]\nname = "t"\ninclude = ["a/*.md"]\nunit = "entry"\nentry_pattern = "^x$"\n',
        '[[find.tiers]]\nname = "t"\ninclude = ["a/*.md"]\nunit = "page"\n',
        '[[find.tiers]]\nname = "t"\ninclude = ["a/*.md"]\n' * 2,
    ],
)
def test_invalid_tiers_are_config_errors(tree, toml):
    root = tree({"a.md": "x\n"})
    with pytest.raises(ConfigError):
        find(root, "x", toml)
    assert load(root, toml)
