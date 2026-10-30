import json

from tests.records.conftest import check, rows


def test_manifest_listed_files_are_frozen_and_counted(tree):
    root = tree(
        {
            "run/hashes.json": json.dumps({"files": {"a.md": "abc", "sub/b.md": "def"}}),
            "run/a.md": "[x](gone.md)",
            "run/sub/b.md": "[x](gone.md)",
            "run/c.md": "[x](gone.md)",
        }
    )
    report = check(root, 'frozen_manifests = ["hashes.json"]\n')
    assert rows(report, "dead-link") == [("error", "run/c.md", 1, "gone.md")]
    assert (report.frozen["dead-link"], report.frozen_in["dead-link"]) == (2, 2)
    assert report.error is None


def test_checksum_manifest_lines_are_read(tree):
    digest = "a" * 64
    root = tree(
        {
            "run/files.sha256": f"{digest}  a.md\n{digest} *b.md\n# comment\n",
            "run/a.md": "[x](gone.md)",
            "run/b.md": "[x](gone.md)",
            "run/c.md": "[x](gone.md)",
        }
    )
    report = check(root, 'frozen_manifests = ["*.sha256"]\n')
    assert [p for _, p, _, _ in rows(report, "dead-link")] == ["run/c.md"]


def test_unreadable_manifest_freezes_its_folder_and_fails_the_run(tree):
    root = tree(
        {
            "run/hashes.json": "{not json",
            "run/a.md": "[x](gone.md)",
            "live/b.md": "[x](gone.md)",
        }
    )
    report = check(root, 'frozen_manifests = ["hashes.json"]\n')
    assert [p for _, p, _, _ in rows(report, "dead-link")] == ["live/b.md"]
    assert report.frozen["dead-link"] == 1
    assert report.error == "unreadable manifest: run/hashes.json"
    assert report.exit_code("never") == 3
