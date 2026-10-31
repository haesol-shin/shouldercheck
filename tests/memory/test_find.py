import json
import math

from shouldercheck.cli import main
from shouldercheck.memory.defaults import MARKER
from tests.memory.conftest import find, paths


def test_score_follows_bm25_on_a_tiny_tree(tree):
    root = tree({"a.md": "alpha", "b.md": "gamma"})
    hit = find(root, "alpha").hits[0]
    # n=2, df=1, tf=1, length equals the average: idf * (k1 + 1) / (1 + k1) = ln 2.
    assert hit["path"] == "a.md"
    assert hit["score"] == round(math.log(2), 3)


def test_a_document_without_a_matching_term_never_appears(tree):
    root = tree({"a.md": "alpha", "b.md": "gamma"})
    assert paths(find(root, "alpha")) == ["a.md"]
    assert find(root, "zzz").hits == []
    assert find(root, "  ").hits == []


def test_field_weights_alias_over_body(tree):
    root = tree(
        {
            "one.md": "---\naliases: [launch]\n---\nplain text\n",
            "two.md": "launch launch launch launch launch\n",
        }
    )
    assert paths(find(root, "launch")) == ["one.md", "two.md"]


def test_weights_are_profile_keys(tree):
    root = tree({"one.md": "---\naliases: [launch]\n---\nplain\n", "two.md": "launch launch\n"})
    toml = "[find.weights]\naliases = 0\n"
    assert paths(find(root, "launch", toml)) == ["two.md"]


def test_exact_alias_beats_a_higher_scoring_body(tree):
    root = tree(
        {
            "target.md": "---\naliases: [Launch Plan]\n---\nnothing\n",
            "noise.md": "launch plan " * 100 + "\n",
        }
    )
    assert paths(find(root, "Launch Plan"))[0] == "target.md"
    assert paths(find(root, "Launch Plan", "[find]\nexact_name_first = false\n"))[0] == "noise.md"


def test_topic_name_beats_file_name_and_priority_orders_inside_the_tier(tree):
    root = tree(
        {
            "alpha.md": "x\n",
            "z/other.md": "# alpha\n",
            "10_Active/alpha.md": "x\n",
        }
    )
    toml = '[[find.priority]]\nglob = "10_Active/**"\nrank = 0\n'
    assert paths(find(root, "alpha", toml)) == ["z/other.md", "10_Active/alpha.md", "alpha.md"]


def test_superseded_by_status_link_and_incoming_link(tree):
    root = tree(
        {
            "old.md": "---\nstatus: superseded\n---\nrelease notes\n",
            "mid.md": "release notes\n\nsuperseded_by: [n](new.md)\n",
            "new.md": "release notes\n",
            "older.md": "release notes\n",
            "newer.md": "supersedes: [o](older.md)\nrelease notes\n",
        }
    )
    hits = {h["path"]: h for h in find(root, "release notes").hits}
    assert hits["old.md"]["superseded"] and hits["old.md"]["replaced_by"] == []
    assert hits["mid.md"]["replaced_by"] == ["new.md"]
    assert hits["older.md"]["replaced_by"] == ["newer.md"]
    assert not hits["new.md"]["superseded"]
    assert hits["old.md"]["score"] < hits["new.md"]["score"]


def test_coverage_power_is_a_profile_key(tree):
    root = tree({"full.md": "alpha beta\n", "half.md": "alpha " * 3 + "\n", "z.md": "gamma\n"})
    assert paths(find(root, "alpha beta"))[0] == "full.md"
    flat = find(root, "alpha beta", "[find]\ncoverage_power = 0\n")
    assert {h["path"] for h in flat.hits} == {"full.md", "half.md"}


def test_ties_break_on_path(tree):
    root = tree({"b.md": "word\n", "a.md": "word\n", "c.md": "word\n"})
    assert paths(find(root, "word")) == ["a.md", "b.md", "c.md"]


def test_neighbours_relation_word_incoming_and_broken(tree):
    root = tree(
        {
            "a.md": "topic here\n\nbasis: [b](b.md) and [gone](missing.md) and [ext](https://x.invalid)\n",
            "b.md": "# B title\n\nsee [a](a.md) and `[c](c.md)`\n",
            "c.md": "[a](a.md)\n",
        }
    )
    hit = find(root, "topic").hits[0]
    assert [(o["relation"], o["path"], o["title"]) for o in hit["outgoing"]] == [
        ("basis", "b.md", "B title"),
        ("basis", None, ""),
    ]
    assert hit["outgoing"][1]["broken"] is True
    assert [i["path"] for i in hit["incoming"]] == ["b.md", "c.md"]


def test_neighbour_limit_counts_the_rest(tree):
    links = "".join(f"[x{i}](t{i}.md)\n" for i in range(5))
    files = {f"t{i}.md": "x\n" for i in range(5)} | {"a.md": "topic\n" + links}
    hit = find(tree(files), "topic", neighbors=2).hits[0]
    assert len(hit["outgoing"]) == 2 and hit["outgoing_total"] == 5


def test_same_alias_documents_are_listed_not_merged(tree):
    root = tree(
        {"a.md": "---\naliases: [Shared]\n---\nx\n", "b.md": "---\naliases: [shared]\n---\nx\n"}
    )
    hits = {h["path"]: h for h in find(root, "shared").hits}
    assert hits["a.md"]["same_alias_as"] == ["b.md"]


def test_generated_files_are_not_searched(tree):
    root = tree({"index.md": MARKER + "\n[w](a.md) widget\n", "a.md": "widget\n"})
    assert paths(find(root, "widget")) == ["a.md"]


def test_snippet_is_masked_and_clipped_and_matched_lists_fields(tree):
    secret = "to" + "ken=" + "hunter2" * 2
    root = tree({"a.md": f"# Plan\n\nthe launch {secret} " + "pad " * 60 + "\n"})
    hit = find(root, "launch").hits[0]
    assert "hunter2" not in hit["snippet"] and len(hit["snippet"]) <= 160
    assert hit["matched"] == ["body"]
    assert "hunter2" not in json.dumps(hit)


def test_long_line_window_starts_near_the_match(tree):
    root = tree({"a.md": "pad " * 80 + "needle here\n"})
    assert "needle" in find(root, "needle").hits[0]["snippet"]


def test_limit(tree):
    root = tree({f"n{i}.md": "word\n" for i in range(5)})
    assert len(find(root, "word", limit=2).hits) == 2


def test_cli_json_text_and_exit_codes(tree, capsys):
    root = tree({"a.md": "widget\n"})
    assert main(["find", "widget", "--root", str(root), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1 and data["hits"][0]["path"] == "a.md"
    assert data["index"]["state"] == "memory"
    assert main(["find", "widget", "--root", str(root)]) == 0
    assert "1. a.md" in capsys.readouterr().out
    assert main(["find", "nothing", "--root", str(root)]) == 0
    assert "no results" in capsys.readouterr().out
    assert main(["find", "x", "--root", str(root / "missing")]) == 3
    (root / "shck.toml").write_text("[find]\nbogus = 1\n", encoding="utf-8")
    assert main(["find", "x", "--root", str(root)]) == 2
    assert "bogus" in capsys.readouterr().err


def test_check_still_accepts_a_find_table(tree):
    root = tree({"a.md": "x\n", "shck.toml": "[find]\nk1 = 1.5\n"})
    assert main(["check", "--root", str(root)]) == 0
