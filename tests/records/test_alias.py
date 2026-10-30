from tests.records.conftest import check


def aliases(root, config=None):
    report = check(root, config)
    return [(f.severity, f.path, f.target) for f in report.findings if f.check == "alias-dup"]


def fm(text):
    return f"---\n{text}\n---\n"


def test_the_same_alias_on_two_documents_is_an_error_for_both(tree):
    root = tree(
        {
            "a.md": fm("aliases: [Shared Name, only-a]"),
            "b.md": fm("aliases:\n  - shared-name"),
            "c.md": fm("aliases: [other]"),
        }
    )
    assert aliases(root) == [
        ("error", "a.md", "Shared Name"),
        ("error", "b.md", "shared-name"),
    ]


def test_normalisation_ignores_case_spaces_dots_hyphens_underscores_and_dots(tree):
    root = tree({"a.md": fm("aliases: [A.B_c-d e·f]"), "b.md": fm("aliases: [abcdef]")})
    assert [s for s, _, _ in aliases(root)] == ["error", "error"]


def test_frozen_copies_own_no_alias(tree):
    root = tree({"a.md": fm("aliases: [x]"), "snap/a.md": fm("aliases: [x]")})
    assert aliases(root, 'frozen = ["snap/**"]\n') == []


def test_alias_equal_to_another_documents_title_or_stem_is_a_candidate(tree):
    root = tree(
        {
            "a.md": fm("aliases: [Release Plan, notes]"),
            "b.md": "# Release plan\n",
            "notes.md": "x",
            "c.md": fm("title: Own\naliases: [own]"),
        }
    )
    assert aliases(root) == [("candidate", "a.md", "Release Plan"), ("candidate", "a.md", "notes")]


def test_aliases_as_a_comma_string_and_the_check_can_be_off(tree):
    root = tree({"a.md": fm("aliases: one, two"), "b.md": fm("aliases: [two]")})
    assert aliases(root) == [("error", "a.md", "two"), ("error", "b.md", "two")]
    assert aliases(root, '[checks]\nalias-dup = "off"\n') == []
