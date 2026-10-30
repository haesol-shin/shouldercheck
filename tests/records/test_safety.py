import os

from tests.records.conftest import check, rows


def test_symlinks_are_skipped_and_listed_never_followed(tree, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.md").write_text("[x](gone.md)", encoding="utf-8")
    root = tree({"a.md": "[x](link.md) [y](dir/secret.md)", "real.md": "x"})
    os.symlink(outside / "secret.md", root / "link.md")
    os.symlink(outside, root / "dir")
    report = check(root)
    assert report.skipped == [("link.md", "symlink")]
    assert [t for _, _, _, t in rows(report, "dead-link")] == ["dir/secret.md", "link.md"]
    assert report.files == 2


def test_unreadable_and_oversized_files_are_listed(tree):
    root = tree({"big.md": "x" * 50, "ok.md": "x"})
    (root / "bin.md").write_bytes(b"\xff\xfe\x00")
    report = check(root, "max_read_chars = 10\n")
    assert report.skipped == [("big.md", "too-large"), ("bin.md", "unreadable")]
    report = check(root, "max_read_chars = 100\n")
    assert report.skipped == [("bin.md", "unreadable")]


def test_frozen_files_are_scanned_but_only_counted(tree):
    root = tree({"snap/a.md": "[x](g.md) [y](h.md)", "snap/b.md": "[x](g.md)", "live.md": "x"})
    report = check(root, 'frozen = ["snap/**"]\n')
    assert report.findings == []
    assert (report.frozen["dead-link"], report.frozen_in["dead-link"]) == (3, 2)
    assert report.frozen_files == 2
    assert "frozen: 3 in 2 files" in report.render_text(20)
