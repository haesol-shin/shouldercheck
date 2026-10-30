from tests.records.conftest import check, rows


def test_resolves_from_the_files_own_folder_without_root_fallback(tree):
    root = tree(
        {
            "top.md": "x",
            "a/ok.md": "[1](../top.md) [2](sub/in.md)",
            "a/sub/in.md": "[3](top.md)",
            "a/bad.md": "[root fallback](top.md)",
        }
    )
    found = rows(check(root), "dead-link")
    assert found == [
        ("error", "a/bad.md", 1, "top.md"),
        ("error", "a/sub/in.md", 1, "top.md"),
    ]


def test_encoded_angled_fragment_and_external_targets(tree):
    root = tree(
        {
            "my note.md": "x",
            "n.md": "[a](my%20note.md#h) [b](<my note.md>) [c](https://x.invalid/a.md)"
            " [d](mailto:a@x.invalid) [e](/abs.md) [f](~/home.md) [g](#same) [h](../up.md)"
            " [i](C:/work/plan.md)",
        }
    )
    assert rows(check(root), "dead-link") == [("error", "n.md", 1, "../up.md")]


def test_label_like_targets_are_candidates_and_paths_are_errors(tree):
    root = tree(
        {
            "n.md": "[a](절제) [b](64-1) [c](gone.md) [d](dir/gone) [e](90% remark) [f](v1.2)",
        }
    )
    got = {t: s for s, _, _, t in rows(check(root), "dead-link")}
    assert got == {
        "절제": "candidate",
        "64-1": "candidate",
        "gone.md": "error",
        "dir/gone": "error",
        "90% remark": "candidate",
        "v1.2": "candidate",
    }


def test_directory_target_needs_link_dirs(tree):
    root = tree({"d/x.md": "x", "n.md": "[a](d/)"})
    assert rows(check(root), "dead-link") == [("error", "n.md", 1, "d/")]
    assert rows(check(root, "[links_opts]\nlink_dirs = true\n"), "dead-link") == []


def test_moved_hint_only_for_a_unique_basename(tree):
    root = tree(
        {
            "n.md": "[a](old/one.md) [b](old/two.md)",
            "new/one.md": "x",
            "p/two.md": "x",
            "q/two.md": "x",
        }
    )
    hints = {f.target: f.hint for f in check(root).findings if f.check == "dead-link"}
    assert hints == {"old/one.md": "moved? new/one.md", "old/two.md": None}


def test_renamed_hint_for_a_dated_successor(tree):
    root = tree({"n.md": "[a](g/core.md) [b](g/solo.md)", "arc/core-20261030.md": "x"})
    hints = {f.target: f.hint for f in check(root).findings if f.check == "dead-link"}
    assert hints == {"g/core.md": "renamed? arc/core-20261030.md", "g/solo.md": None}


def test_links_to_files_outside_the_include_scope_still_exist(tree):
    root = tree({"n.md": "[a](pic.png) [b](.hidden/x.md)", "pic.png": "x", ".hidden/x.md": "x"})
    assert rows(check(root), "dead-link") == []
