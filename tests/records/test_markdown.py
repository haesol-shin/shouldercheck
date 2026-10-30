from shouldercheck.records import markdown


def targets(text: str) -> list[str]:
    return [link.target for link in markdown.parse(text).links]


def test_links_in_every_kind_of_code_are_ignored():
    text = "\n".join(
        [
            "---",
            "see: [a](front.md)",
            "---",
            "[ok](ok.md)",
            "`[x](inline.md)` and ``[y](`two`.md)``",
            "```",
            "[f](fenced.md)",
            "```",
            "~~~~",
            "```",
            "[t](tilde.md)",
            "~~~~",
            "",
            "    [i](indented.md)",
            "",
            "- item",
            "  ```",
            "  [l](listed.md)",
            "  ```",
            "",
            "      [n](list-continuation.md)",
            "> ```",
            "> [q](quoted.md)",
            "> ```",
            "[after](after.md)",
        ]
    )
    assert targets(text) == ["ok.md", "list-continuation.md", "after.md"]


def test_indented_line_inside_a_paragraph_is_not_code():
    assert targets("para\n    [x](cont.md)") == ["cont.md"]


def test_unclosed_front_matter_is_prose():
    assert targets("---\n[a](a.md)") == ["a.md"]


def test_target_forms():
    text = (
        '[a](<with space.md>) [b](a(1).md) [c](t.md "title") [d](x.md) y [e](<q.md> "t") '
        "[empty]() \\[no](esc.md) [f](a\\)b.md)"
    )
    assert targets(text) == ["with space.md", "a(1).md", "t.md", "x.md", "q.md", "a)b.md"]


def test_prose_in_parentheses_keeps_its_spaces():
    links = markdown.parse("[ref](90% remark here)").links
    assert [(link.target, link.angled) for link in links] == [("90% remark here", False)]


def test_unclosed_target_is_not_a_link():
    assert targets("[a](b.md and more text") == []


def test_inline_ignore_needs_markup_outside_code():
    text = '<!-- shck: ignore dead-link, orphan reason="why" -->\n`<!-- shck: ignore size -->`'
    ignores = markdown.parse(text).ignores
    assert [(i.line, i.checks, i.reason) for i in ignores] == [(1, ("dead-link", "orphan"), "why")]
