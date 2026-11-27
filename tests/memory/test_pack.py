import hashlib
import json
from pathlib import Path

import pytest

from shouldercheck.cli import main
from shouldercheck.memory.pack import PackError, pack, pick
from shouldercheck.memory.settings import resume_settings
from shouldercheck.records.config import load_config
from tests.memory.conftest import load

EXAMPLE = Path(__file__).parents[2] / "docs" / "examples" / "shck.toml"
NOTES = """---
title: Notes
---
# Notes

intro

## Color

blue

### Shade (dark)

navy

```md
# Color
```

## Colors

red

## Size

large
"""


def text(root, selector, config=None):
    return pick(load(root, config), selector).text


def test_whole_file_has_a_receipt_of_its_own_text(tree):
    root = tree({"a.md": "# A\n\nbody\n"})
    piece = pick(load(root), "a.md")
    assert piece.text == "# A\n\nbody"
    assert (piece.chars, piece.sha256) == (9, hashlib.sha256(b"# A\n\nbody").hexdigest())


def test_exact_heading_takes_its_nested_levels_and_stops_at_a_peer(tree):
    root = tree({"n.md": NOTES})
    section = text(root, "n.md#Size")
    assert section == "## Size\n\nlarge"
    # `## Color` runs through its `###` child and stops before the next `##`.
    color = text(root, "n.md#Color")
    assert color.startswith("## Color\n\nblue\n\n### Shade (dark)") and color.endswith("```")
    assert "## Colors" not in color


def test_prefix_matches_after_a_space_or_a_parenthesis_only(tree):
    root = tree({"n.md": NOTES})
    assert text(root, "n.md#Shade").startswith("### Shade (dark)")
    assert text(root, "n.md#Colors").endswith("red")
    with pytest.raises(PackError, match="no heading matches"):
        pick(load(root), "n.md#Sha")  # a prefix inside a word is not a match


def test_heading_inside_fenced_code_does_not_count_or_end_a_section(tree):
    root = tree({"n.md": NOTES})
    # `# Color` appears only in the fence, so `Color` is one heading and the fence stays inside.
    assert "```md\n# Color\n```" in text(root, "n.md#Color")


def test_last_section_runs_to_the_end_of_the_file(tree):
    root = tree({"a.md": "# A\n\n## Last\n\none\n\n### Deeper\n\ntwo\n"})
    assert text(root, "a.md#Last") == "## Last\n\none\n\n### Deeper\n\ntwo"


def test_a_higher_level_heading_ends_a_lower_section(tree):
    root = tree({"a.md": "## Low\n\nx\n\n# High\n\ny\n"})
    assert text(root, "a.md#Low") == "## Low\n\nx"


def test_closing_hashes_are_not_part_of_the_heading(tree):
    root = tree({"a.md": "## Name ##\n\nx\n"})
    assert text(root, "a.md#Name") == "## Name ##\n\nx"


def test_a_prefix_that_also_fits_a_sibling_heading_is_ambiguous(tree):
    root = tree({"n.md": "## Color\n\nx\n\n## Color scheme\n\ny\n"})
    with pytest.raises(PackError, match=r"'n.md#Color': 2 headings match"):
        pick(load(root), "n.md#Color")
    assert text(root, "n.md#Color scheme") == "## Color scheme\n\ny"


def test_ambiguous_and_missing_selectors_name_the_selector(tree, capsys):
    root = tree({"a.md": "# One\n\n# One more\n\nx\n"})
    with pytest.raises(PackError, match=r"'a.md#One': 2 headings match \(lines 1, 3\)"):
        pick(load(root), "a.md#One")
    assert main(["pack", "a.md#One", "--root", str(root)]) == 2
    assert "a.md#One" in capsys.readouterr().err
    assert main(["pack", "a.md#Gone", "--root", str(root)]) == 2
    assert main(["pack", "gone.md", "--root", str(root)]) == 2
    assert main(["pack", "a.md#", "--root", str(root)]) == 2


def test_paths_may_not_leave_the_record_base(tree, tmp_path):
    root = tree({"a.md": "# A\n"})
    (tmp_path / "outside.md").write_text("# Secret\n", encoding="utf-8")
    (root / "link.md").symlink_to(tmp_path / "outside.md")
    for selector in ("../outside.md", str(tmp_path / "outside.md"), "link.md"):
        with pytest.raises(PackError, match="leaves the record base"):
            pick(load(root), selector)


def test_receipt_ignores_line_endings_and_trailing_blank_lines(tree):
    body = "## A\n\nbody\n\n## B\n\nb\n"
    root = tree({"a.md": body})
    unix = pick(load(root), "a.md#A"), pick(load(root), "a.md")
    (root / "a.md").write_bytes((body + "\n\n").replace("\n", "\r\n").encode())
    assert (pick(load(root), "a.md#A"), pick(load(root), "a.md")) == unix
    assert unix[0].text == "## A\n\nbody" and unix[1].text == body.rstrip()


def test_output_is_byte_identical_and_fences_outgrow_the_text(tree, capsys):
    root = tree({"a.md": "# A\n\n```py\nx\n```\n", "b.md": "# B\n\n가나다\n"})
    argv = ["pack", "a.md", "b.md#B", "--root", str(root)]
    assert main(argv) == 0
    first = capsys.readouterr().out
    assert main(argv) == 0
    assert capsys.readouterr().out == first
    assert "````md\n# A\n\n```py\nx\n```\n````\n" in first
    body = "# B\n\n가나다"
    receipt = f"{hashlib.sha256(body.encode()).hexdigest()}  {len(body)}  b.md#B\n```\n"
    assert first.endswith(receipt)
    assert first.index("[1] a.md") < first.index("[2] b.md#B") < first.index("\nreceipt\n")


def test_json_carries_the_same_receipt(tree, capsys):
    root = tree({"a.md": "# A\n\nx\n"})
    assert main(["pack", "a.md#A", "--json", "--root", str(root)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "total_chars": 6,
        "sections": [
            {
                "selector": "a.md#A",
                "chars": 6,
                "sha256": hashlib.sha256(b"# A\n\nx").hexdigest(),
                "text": "# A\n\nx",
            }
        ],
    }


def test_resume_table_is_the_default_list_and_arguments_replace_it(tree, capsys):
    root = tree(
        {
            "a.md": "# A\n\n## Now\n\nstate\n",
            "b.md": "# B\n",
            "shck.toml": '[resume]\nselectors = ["a.md#Now"]\n',
        }
    )
    assert main(["pack", "--root", str(root), "--json"]) == 0
    assert [s["selector"] for s in json.loads(capsys.readouterr().out)["sections"]] == ["a.md#Now"]
    assert main(["pack", "b.md", "--root", str(root), "--json"]) == 0
    assert [s["selector"] for s in json.loads(capsys.readouterr().out)["sections"]] == ["b.md"]


def test_no_selectors_anywhere_is_an_error(tree, capsys):
    root = tree({"a.md": "# A\n"})
    assert main(["pack", "--root", str(root)]) == 2
    assert "no selectors" in capsys.readouterr().err


def test_cap_stops_instead_of_truncating(tree, capsys):
    root = tree({"a.md": "x" * 60, "b.md": "y" * 60, "shck.toml": "[resume]\nmax_chars = 100\n"})
    assert main(["pack", "a.md", "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["pack", "a.md", "b.md", "--root", str(root)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "120 characters selected, over max_chars 100" in captured.err
    with pytest.raises(PackError, match="max_chars 100"):
        pack(load(root), ("a.md", "b.md"), 100)


def test_bad_resume_table_is_a_config_error(tree, capsys):
    root = tree({"a.md": "# A\n", "shck.toml": "[resume]\nselector = []\n"})
    assert main(["pack", "a.md", "--root", str(root)]) == 2
    assert "unknown key(s): selector" in capsys.readouterr().err


def test_documented_example_profile_resume_table_works(tree):
    root = tree({"projects/README.md": "# Projects\n\nlist\n"})
    cfg = load_config(EXAMPLE, root, root)
    settings = resume_settings(cfg)
    assert settings.selectors == ("projects/README.md",)
    assert [p.chars for p in pack(cfg, settings.selectors, settings.max_chars)] == [16]
