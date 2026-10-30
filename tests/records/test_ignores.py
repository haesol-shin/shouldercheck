from tests.records.conftest import check, rows


def test_per_path_ignore_with_reason_suppresses_and_counts(tree):
    root = tree({"fx/a.md": "[x](g.md) [y](h.md)", "b.md": "[x](g.md)"})
    toml = '[[per-path-ignores]]\nglob = "fx/**"\nchecks = ["dead-link"]\nreason = "fixture copy"\n'
    report = check(root, toml)
    assert rows(report, "dead-link") == [("error", "b.md", 1, "g.md")]
    assert report.suppressed["dead-link"] == 2
    assert report.to_json()["summary"]["by_check"]["dead-link"]["suppressed"] == 2


def test_per_path_ignore_without_reason_still_applies_but_warns(tree):
    root = tree({"fx/a.md": "[x](g.md)"})
    toml = '[[per-path-ignores]]\nglob = "fx/**"\nchecks = ["dead-link"]\n'
    report = check(root, toml)
    assert rows(report, "dead-link") == []
    assert rows(report, "ignore-without-reason") == [("warn", "shck.toml", None, "fx/**")]


def test_inline_ignore_covers_its_line_and_the_next_only(tree):
    text = "\n".join(
        [
            '<!-- shck: ignore dead-link reason="draft" -->',
            "[a](g1.md)",
            "[b](g2.md)",
            '[c](g3.md) <!-- shck: ignore dead-link reason="same line" -->',
            '<!-- shck: ignore size reason="other check" -->',
            "[d](g4.md)",
        ]
    )
    report = check(tree({"n.md": text}))
    assert rows(report, "dead-link") == [
        ("error", "n.md", 3, "g2.md"),
        ("error", "n.md", 6, "g4.md"),
    ]
    assert report.suppressed["dead-link"] == 2


def test_inline_ignore_without_reason_warns_and_still_suppresses(tree):
    report = check(tree({"n.md": "<!-- shck: ignore dead-link -->\n[a](g.md)"}))
    assert rows(report, "dead-link") == []
    assert rows(report, "ignore-without-reason") == [("warn", "n.md", 1, "dead-link")]


def test_inline_ignore_inside_a_code_block_is_not_a_directive(tree):
    text = "```\n<!-- shck: ignore dead-link -->\n```\n[a](g.md)"
    report = check(tree({"n.md": text}))
    assert len(rows(report, "dead-link")) == 1
    assert rows(report, "ignore-without-reason") == []


def test_skipping_the_reason_check_hides_its_warning(tree):
    report = check(
        tree({"n.md": "<!-- shck: ignore dead-link -->"}), skip={"ignore-without-reason"}
    )
    assert report.findings == []
