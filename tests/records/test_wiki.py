from tests.records.conftest import check, rows


def dead(root, config=None):
    return [(s, t) for s, _, _, t in rows(check(root, config), "dead-link")]


def test_stem_resolution_is_case_insensitive_and_ignores_label_and_heading(tree):
    root = tree(
        {"a/Design Note.md": "x", "n.md": "[[design note]] [[Design Note|text]] [[design note#h]]"}
    )
    assert dead(root) == []


def test_missing_wiki_target_is_a_candidate_unless_path_like(tree):
    root = tree({"n.md": "[[Uncaptioned image]] [[folder/gone]]"})
    assert dead(root) == [("candidate", "[[Uncaptioned image]]"), ("error", "[[folder/gone]]")]


def test_two_files_with_the_same_stem_are_ambiguous_never_guessed(tree):
    root = tree({"a/x.md": "x", "b/x.md": "x", "n.md": "[[x]] [[a/x]]"})
    report = check(root)
    found = [(f.severity, f.target, f.hint) for f in report.findings]
    assert found == [("candidate", "[[x]]", "a/x.md, b/x.md")]


def test_path_and_title_resolution_modes(tree):
    files = {"a/x.md": "# Big Idea\n", "b/y.md": "x", "n.md": "[[a/x]] [[Big Idea]] [[y]]"}
    root = tree(files)
    assert dead(root, '[links_opts]\nwiki_resolve = "path"\n') == [
        ("candidate", "[[Big Idea]]"),
        ("candidate", "[[y]]"),
    ]
    assert dead(root, '[links_opts]\nwiki_resolve = "title"\n') == []


def test_attachment_names_resolve_by_basename(tree):
    root = tree({"img/p.png": "x", "n.md": "![[p.png]] ![[q.png]]"})
    assert dead(root) == [("error", "[[q.png]]")]


def test_wiki_style_can_be_disabled(tree):
    root = tree({"n.md": "[[nothing]]"})
    assert dead(root, 'links = ["markdown"]\n') == []


def test_backtick_paths_are_never_dead_unless_asked(tree):
    root = tree(
        {
            "d/real.md": "x",
            "n.md": "`d/real.md` `d/gone.md` `shck check` `index.md` `https://x.invalid/a.md`",
        }
    )
    assert dead(root) == []
    assert dead(root, 'links = ["markdown", "backtick"]\n') == []
    both = "[links_opts]\nbacktick_dead = true\n"
    assert dead(root, 'links = ["markdown", "backtick"]\n' + both) == [("candidate", "d/gone.md")]
