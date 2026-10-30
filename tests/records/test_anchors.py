from tests.records.conftest import check, rows


def anchors(root, config=None):
    return [(p, t) for _, p, _, t in rows(check(root, config), "dead-anchor")]


def test_hangul_heading_slug_and_missing_anchor(tree):
    root = tree(
        {
            "t.md": "# 점검 보고서 v2\n\n## What's new?\n",
            "n.md": "[a](t.md#점검-보고서-v2) [b](t.md#whats-new) [d](t.md#missing)"
            " [c](t.md#%EC%A0%90%EA%B2%80-보고서-v2)",
        }
    )
    assert anchors(root) == [("n.md", "t.md#missing")]


def test_duplicate_headings_get_numeric_suffixes(tree):
    root = tree(
        {
            "t.md": "# Notes\n## Notes\n## Notes\n",
            "n.md": "[a](t.md#notes) [b](t.md#notes-1) [c](t.md#notes-2) [d](t.md#notes-3)",
        }
    )
    assert anchors(root) == [("n.md", "t.md#notes-3")]


def test_same_file_fragment_uses_the_files_own_headings(tree):
    root = tree({"n.md": "# Top\n[a](#top) [b](#nope)\n"})
    assert anchors(root) == [("n.md", "#nope")]


def test_headings_in_code_do_not_count(tree):
    root = tree({"t.md": "```\n# Hidden\n```\n", "n.md": "[a](t.md#hidden)"})
    assert anchors(root) == [("n.md", "t.md#hidden")]


def test_inline_formatting_is_not_part_of_the_slug(tree):
    root = tree(
        {"t.md": "## Use `shck` [now](x.md) **fast**\n", "n.md": "[a](t.md#use-shck-now-fast)"}
    )
    assert anchors(root) == []


def test_slug_option_switches_the_rule(tree):
    files = {"t.md": "# A B\n# A B\n", "n.md": "[a](t.md#a-b_1) [b](t.md#a-b-1) [c](t.md#A B)"}
    root = tree(files)
    assert anchors(root, '[links_opts]\nslug = "mkdocs"\n') == [("n.md", "t.md#a-b-1")]
    assert anchors(root, '[links_opts]\nslug = "obsidian"\n') == [
        ("n.md", "t.md#a-b-1"),
        ("n.md", "t.md#a-b_1"),
    ]


def test_custom_and_html_ids_only_when_enabled(tree):
    root = tree(
        {
            "t.md": '# Title {#custom}\n<a id="anchor"></a>\n',
            "n.md": "[a](t.md#custom) [b](t.md#anchor)",
        }
    )
    assert len(anchors(root)) == 2
    assert anchors(root, "[links_opts]\nheading_ids = true\nhtml_ids = true\n") == []


def test_block_ids_and_non_markdown_targets_are_never_flagged(tree):
    root = tree(
        {"t.md": "x", "n.md": "[a](t.md#^abc123) [b](p.pdf#page=2) [c](t.md#)", "p.pdf": "x"}
    )
    assert anchors(root) == []


def test_wiki_heading_links_are_checked(tree):
    root = tree({"t.md": "## Part One\n", "n.md": "[[t#Part One]] [[t#Part Two]] [[#Local]]"})
    assert anchors(root) == [("n.md", "[[#Local]]"), ("n.md", "[[t#Part Two]]")]
