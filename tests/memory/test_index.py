import json
import os

import pytest

from shouldercheck.cli import main
from shouldercheck.memory.defaults import MARKER
from shouldercheck.records.config import ConfigError
from tests.memory.conftest import find, load, paths

BASE = """
[index]
title = "Map"
header = ["Locations only."]
top_files = ["TOP.md", "missing.md"]

[[index.sections]]
id = "notes"
title = "Notes"
root = "notes"
cap = 3
note = "one file per topic"

[[index.sections]]
id = "people"
title = "People"
root = "notes/people"
cap = 5

[[index.sections]]
id = "log"
title = "Log"
root = "log"
mode = "recent"
cap = 2
order = "name-desc"

[[index.sections]]
id = "inbox"
title = "Inbox"
root = "inbox"
mode = "count"
"""


def files(extra=None):
    base = {
        "TOP.md": "# Top page\n",
        "notes/a.md": "# Alpha\n",
        "notes/b.md": "---\ntitle: Bravo\n---\nbody\n",
        "notes/sub/c.md": "# Charlie\n",
        "notes/sub/d.md": "# Delta\n",
        "notes/e.md": "# Echo\n",
        "notes/people/p1.md": "# Pat\n",
        "log/2026-10-01.md": "# one\n",
        "log/2026-10-02.md": "# two\n",
        "log/2026-10-03.md": "# three\n",
        "inbox/x/1.md": "# x1\n",
        "inbox/x/2.md": "# x2\n",
        "inbox/3.md": "# r\n",
        "shck.toml": BASE,
    }
    return base | (extra or {})


def index(root, *args):
    return main(["index", "--root", str(root), *args])


def test_map_layout_caps_and_section_index(tree, capsys):
    root = tree(files())
    assert index(root) == 0
    text = (root / "index.md").read_text("utf-8")
    assert text.splitlines()[0] == MARKER and text.splitlines()[1] == "# Map"
    assert "> Locations only." in text and "- [Top page](<TOP.md>)" in text
    assert "missing.md" not in text
    notes = text.split("## Notes")[1].split("## People")[0]
    assert "_one file per topic_" in notes
    # cap 3 over 5 files; the deeper root keeps notes/people/p1.md out of this section.
    assert notes.count("](<") == 4 and "_2 more, see [notes/index.md](<notes/index.md>)_" in notes
    assert "[Alpha](<notes/a.md>)" in notes and "[Charlie]" not in notes
    assert "[Pat](<notes/people/p1.md>)" in text.split("## People")[1].split("## Log")[0]
    assert "[Bravo](<notes/b.md>)" in notes
    log = text.split("## Log")[1].split("## Inbox")[0]
    assert log.index("[three]") < log.index("[two]") and "- _1 more_" in log
    assert "[three](<log/2026-10-03.md>)" in log and "[one]" not in log
    inbox = text.split("## Inbox")[1]
    assert "- `inbox/`: 1 files" in inbox and "- `inbox/x/`: 2 files" in inbox
    section = (root / "notes/index.md").read_text("utf-8")
    assert section.startswith(MARKER) and section.count("](<") == 5
    assert "(<a.md>)" in section and "  - [Charlie](<sub/c.md>)" in section
    assert "- `sub/`" in section
    assert not (root / "log/index.md").exists() and not (root / "notes/people/index.md").exists()


def test_second_run_is_a_no_op_and_bytes_are_stable(tree):
    root = tree(files())
    index(root)
    before = {p: (root / p).read_bytes() for p in ("index.md", "notes/index.md")}
    stamps = {p: (root / p).stat().st_mtime_ns for p in before}
    os.utime(root / "index.md", ns=(1, 1))
    assert index(root, "--check") == 0
    assert index(root) == 0
    assert (root / "index.md").stat().st_mtime_ns == 1  # untouched, not rewritten
    assert {p: (root / p).read_bytes() for p in before} == before
    assert stamps["notes/index.md"] == (root / "notes/index.md").stat().st_mtime_ns


def test_check_writes_nothing_and_exits_1_when_stale(tree, capsys):
    root = tree(files())
    assert index(root, "--check", "--diff") == 1
    out = capsys.readouterr().out
    assert "+++ b/index.md" in out and "+# Map" in out
    assert not (root / "index.md").exists()
    index(root)
    (root / "notes/f.md").write_text("# Foxtrot\n", encoding="utf-8")
    assert index(root, "--check") == 1
    assert "stale" in capsys.readouterr().out
    index(root)
    assert index(root, "--check") == 0


def test_a_hand_written_file_at_a_generated_path_stops_everything(tree, capsys):
    root = tree(files({"notes/index.md": "# my own notes index\n"}))
    assert index(root) == 3
    assert "notes/index.md" in capsys.readouterr().out
    assert not (root / "index.md").exists()
    assert (root / "notes/index.md").read_text("utf-8") == "# my own notes index\n"


def test_adopt_takes_over_the_map_only(tree):
    root = tree(files({"index.md": "# old hand-made map\n"}))
    assert index(root) == 3 and (root / "index.md").read_text("utf-8").startswith("# old")
    assert index(root, "--adopt") == 0
    assert (root / "index.md").read_text("utf-8").startswith(MARKER)
    assert index(root) == 0
    root2 = tree(files({"notes/index.md": "# mine\n"}))
    assert index(root2, "--adopt") == 3


def test_shrink_loop_keeps_every_section(tree):
    many = {f"notes/n{i:02}.md": f"# Note {i}\n" for i in range(30)}
    extra = {"shck.toml": BASE.replace("cap = 3", "cap = 30") + "[size]\nmap_budget_chars = 900\n"}
    root = tree(files(many | extra))
    assert index(root, "--format", "json") == 0
    text = (root / "index.md").read_text("utf-8")
    assert len(text) <= 900
    for heading in ("## Notes", "## People", "## Log", "## Inbox"):
        assert heading in text
    assert text.count("](<notes/") >= 1 and "[Pat](<notes/people/p1.md>)" in text
    assert (root / "notes/index.md").exists()


def test_shrink_takes_from_the_largest_section_first(tree):
    many = {f"notes/n{i:02}.md": f"# Note {i}\n" for i in range(30)}
    cfg = BASE.replace("cap = 3", "cap = 30") + "[size]\nmap_budget_chars = 1100\n"
    root = tree(files(many | {"shck.toml": cfg}))
    index(root)
    text = (root / "index.md").read_text("utf-8")
    assert "[Pat](<notes/people/p1.md>)" in text and "[three](<log/2026-10-03.md>)" in text


def test_big_sections_split_into_subfolder_indexes_without_dead_links(tree, capsys):
    many = {
        f"notes/g{g}/n{i:02}.md": f"# Group {g} note {i}\n" for g in range(4) for i in range(12)
    }
    cfg = BASE + "[size]\nmap_budget_chars = 1200\n"
    root = tree(files(many | {"shck.toml": cfg}))
    assert index(root) == 0
    assert (root / "notes/g0/index.md").read_text("utf-8").startswith(MARKER)
    top = (root / "notes/index.md").read_text("utf-8")
    assert "[g0/](<g0/index.md>) (12 files)" in top and len(top) <= 1200
    capsys.readouterr()
    assert main(["check", "--root", str(root), "--format", "json"]) == 0
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert [f for f in findings if f["check"] == "dead-link"] == []


def test_depth_limit_prints_counts_and_a_note(tree, capsys):
    deep = {f"notes/a/b/c/d/n{i:02}.md": f"# Deep note number {i}\n" for i in range(40)}
    cfg = BASE + "[size]\nmap_budget_chars = 700\n"
    root = tree(files(deep | {"shck.toml": cfg}))
    assert index(root, "--format", "json") == 0
    data = json.loads(capsys.readouterr().out)
    assert any("depth limit" in note for note in data["notes"])
    assert "`c/`: 40 files" in (root / "notes/a/b/index.md").read_text("utf-8")


def test_json_report(tree, capsys):
    root = tree(files())
    index(root, "--format", "json")
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1 and data["map"]["budget"] == 24000
    assert {f["path"] for f in data["files"]} == {"index.md", "notes/index.md"}
    assert data["written"] == ["index.md", "notes/index.md"] or set(data["written"]) == {
        "index.md",
        "notes/index.md",
    }


def test_generated_files_are_not_entries_and_not_searched(tree):
    root = tree(files())
    index(root)
    index(root)
    text = (root / "index.md").read_text("utf-8")
    assert "](<notes/index.md>)" in text and "index.md>) " not in text.split("## Notes")[0]
    assert "[Map]" not in text
    assert paths(find(root, "Alpha")) == ["notes/a.md"]


@pytest.mark.parametrize(
    "toml",
    [
        "[index]\ntitle = 'x'\n",
        BASE + '\n[[index.sections]]\nid = "notes"\nroot = "z"\n',
        BASE + '\n[[index.sections]]\nid = "dup"\nroot = "notes"\n',
        BASE.replace('mode = "recent"', 'mode = "stack"'),
        BASE.replace('root = "log"', 'root = "../log"'),
        BASE.replace('order = "name-desc"', 'order = "sideways"'),
        BASE.replace("cap = 3", "cap = 0"),
        BASE + "bogus = 1\n",
        "[index]\nmap = ''\n[[index.sections]]\nid='a'\nroot='a'\n",
    ],
)
def test_invalid_index_profiles_exit_2(tree, toml, capsys):
    root = tree({"a/x.md": "x\n", "shck.toml": toml})
    assert index(root) == 2
    assert capsys.readouterr().err.startswith("shck:")


def test_no_sections_hint(tree, capsys):
    root = tree({"a.md": "x\n"})
    assert index(root) == 2
    assert "[[index.sections]]" in capsys.readouterr().err


def test_missing_root_exits_3(tree, tmp_path):
    assert main(["index", "--root", str(tmp_path / "nope")]) in (2, 3)


def test_config_errors_raise_for_library_callers(tree):
    from shouldercheck.memory.settings import index_settings

    with pytest.raises(ConfigError):
        index_settings(load(tree({"a.md": "x\n"}), "[index]\nmode = 1\n"))


def dead_links(root, capsys):
    capsys.readouterr()
    main(["check", "--root", str(root), "--format", "json"])
    findings = json.loads(capsys.readouterr().out)["findings"]
    return [f for f in findings if f["check"] == "dead-link"]


def test_map_in_a_subfolder_links_relative_to_the_map(tree, capsys):
    cfg = BASE.replace('title = "Map"', 'title = "Map"\nmap = "maps/index.md"')
    root = tree(files({"shck.toml": cfg}))
    assert index(root) == 0
    text = (root / "maps/index.md").read_text("utf-8")
    assert "[Top page](<../TOP.md>)" in text and "[Alpha](<../notes/a.md>)" in text
    assert "see [notes/index.md](<../notes/index.md>)" in text
    assert dead_links(root, capsys) == []


def test_a_folder_with_files_and_subfolders_prints_its_heading_once(tree):
    cfg = BASE.replace("cap = 3", "cap = 30")
    root = tree(files({"notes/sub/z.md": "# Zulu\n", "notes/zz.md": "# Zed\n", "shck.toml": cfg}))
    index(root)
    text = (root / "index.md").read_text("utf-8")
    assert text.count("- `notes/sub/`") == 1
    assert text.index("[Zed]") < text.index("- `notes/sub/`")


def test_section_indexes_left_by_an_over_budget_run_become_pointers(tree, capsys):
    many = {
        f"notes/g{g}/n{i:02}.md": f"# Group {g} note {i}\n" for g in range(4) for i in range(12)
    }
    small = BASE + "[size]\nmap_budget_chars = 1200\n"
    root = tree(files(many | {"shck.toml": small}))
    assert index(root) == 0
    old = root / "notes/g0/index.md"
    assert old.read_text("utf-8").count("](<") == 12
    (root / "shck.toml").write_text(BASE.replace("cap = 3", "cap = 80"), encoding="utf-8")
    assert index(root, "--check", "--diff") == 1
    out = capsys.readouterr().out
    assert "notes/g0/index.md" in out and "stale" in out
    assert index(root) == 0
    pointer = old.read_text("utf-8")
    assert pointer.startswith(MARKER) and pointer.count("\n") == 2
    assert "(<../index.md>)" in pointer or "(<../../index.md>)" in pointer
    assert index(root, "--check") == 0
    assert dead_links(root, capsys) == []


def test_switching_a_section_to_count_turns_its_old_index_into_a_pointer(tree, capsys):
    root = tree(files())
    assert index(root) == 0
    old = root / "notes/index.md"
    assert old.read_text("utf-8").count("](<") >= 3
    switched = BASE.replace('root = "notes"\ncap = 3\n', 'root = "notes"\nmode = "count"\n')
    assert switched != BASE
    (root / "shck.toml").write_text(switched, encoding="utf-8")
    assert index(root, "--check", "--diff") == 1
    assert "notes/index.md" in capsys.readouterr().out
    assert index(root) == 0
    pointer = old.read_text("utf-8")
    assert pointer.startswith(MARKER) and pointer.count("\n") == 2
    assert "(<../index.md>)" in pointer
    assert index(root, "--check") == 0
