import os
import time

from tests.records.conftest import check, rows

SCOPE = '[orphans]\nscope = ["notes/**"]\n'


def orphans(root, config):
    return [(s, p) for s, p, _, _ in rows(check(root, config), "orphan")]


def test_no_scope_means_no_check(tree):
    assert check(tree({"notes/a.md": "x"})).findings == []


def test_file_without_inbound_is_a_warning_and_self_links_do_not_count(tree):
    root = tree(
        {
            "notes/a.md": "[me](a.md) [b](b.md)",
            "notes/b.md": "x",
            "notes/c.md": "[self](c.md)",
            "other.md": "[a](notes/a.md)",
        }
    )
    assert orphans(root, SCOPE) == [("warn", "notes/c.md")]


def test_a_catalog_alone_makes_a_candidate_not_a_warning(tree):
    root = tree(
        {
            "index.md": "[a](notes/a.md) [b](notes/b.md)",
            "notes/a.md": "x",
            "notes/b.md": "[a](a.md)",
        }
    )
    toml = SCOPE + 'catalog = ["index.md"]\n'
    assert orphans(root, toml) == [("candidate", "notes/b.md")]
    # Without the catalog rule the index is an ordinary source.
    assert orphans(root, SCOPE) == []


def test_exempt_globs_and_names(tree):
    root = tree({"notes/README.md": "x", "notes/j/intent.md": "x", "notes/j/result-v2.md": "x"})
    toml = SCOPE + 'exempt = ["**/README.md"]\nexempt_names = ["intent.md", "result-v*.md"]\n'
    assert orphans(root, toml) == []


def test_backtick_paths_are_inbound_only_when_enabled(tree):
    root = tree({"notes/a.md": "x", "other.md": "see `notes/a.md:12`"})
    assert orphans(root, SCOPE) == [("warn", "notes/a.md")]
    assert orphans(root, 'links = ["markdown", "wiki", "backtick"]\n' + SCOPE) == []


def test_wiki_links_are_inbound_and_ambiguous_ones_are_not(tree):
    root = tree({"notes/a.md": "x", "notes/b.md": "x", "x/b.md": "x", "o.md": "[[a]] [[b]]"})
    assert orphans(root, SCOPE) == [("warn", "notes/b.md")]


def test_frozen_files_still_count_as_link_sources(tree):
    root = tree({"notes/a.md": "x", "snap/old.md": "[a](../notes/a.md)"})
    assert orphans(root, 'frozen = ["snap/**"]\n' + SCOPE) == []


FOLDERS = SCOPE + 'catalog = ["index.md"]\nexempt_names = ["intent.md"]\n'
FOLDERS += 'unit = "folder"\nfolder_depth = 2\n'


def test_folder_unit_needs_inbound_from_outside_the_folder(tree):
    root = tree(
        {
            "notes/job-a/intent.md": "x",
            "notes/job-a/result.md": "[i](intent.md)",
            "notes/job-b/result.md": "x",
            "notes/job-b/deep/extra.md": "x",
            "notes/job-c/result.md": "x",
            "notes/job-d/result.md": "x",
            "notes/guide.md": "[b](job-b/result.md)",
            "index.md": "[c](notes/job-c/result.md)",
        }
    )
    got = {p: (s, m) for s, p, m in _with_message(root, FOLDERS)}
    assert got == {
        "notes/guide.md": ("warn", "no inbound link"),
        "notes/job-a/": ("warn", "no inbound from outside the folder (1 files)"),
        "notes/job-c/": ("candidate", "only linked from a catalog (1 files)"),
        "notes/job-d/": ("warn", "no inbound from outside the folder (1 files)"),
    }


def _with_message(root, config):
    return [
        (f.severity, f.path, f.message) for f in check(root, config).findings if f.check == "orphan"
    ]


def test_folder_unit_counts_members_below_the_depth(tree):
    root = tree(
        {"notes/job/a.md": "x", "notes/job/sub/b.md": "x", "o.md": "[b](notes/job/sub/b.md)"}
    )
    toml = SCOPE + 'unit = "folder"\nfolder_depth = 2\n'
    assert orphans(root, toml) == []


def test_grace_days_hides_young_files(tree):
    root = tree({"notes/new.md": "x", "notes/old.md": "x"})
    long_ago = time.time() - 10 * 86400
    os.utime(root / "notes/old.md", (long_ago, long_ago))
    toml = SCOPE + "grace_days = 3\n"
    assert orphans(root, toml) == [("warn", "notes/old.md")]
