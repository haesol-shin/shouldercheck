import hashlib
import json
import os
from pathlib import Path

from shouldercheck.cli import main
from tests.records.conftest import check


def snapshot(root: Path) -> dict[str, str]:
    out = {}
    for folder, _, names in os.walk(root):
        for name in names:
            path = Path(folder, name)
            out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_json_shape_and_ordering(tree, capsys):
    root = tree({"b.md": "[x](z.md)", "a.md": "[x](y.md) [y](q)", "frozen/f.md": "[x](gone.md)"})
    toml = 'frozen = ["frozen/**"]\n'
    (root / "shck.toml").write_text(toml, encoding="utf-8")
    assert main(["check", "--root", str(root), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1
    assert set(data) == {"schema_version", "root", "config", "scan", "summary", "findings"}
    assert data["config"] == "shck.toml"
    assert data["scan"] == {"files": 3, "frozen": 1, "skipped": []}
    assert data["summary"] == {
        "error": 2,
        "warn": 0,
        "candidate": 1,
        "suppressed": 0,
        "by_check": {"dead-link": {"candidate": 1, "error": 2, "frozen": 1, "frozen_files": 1}},
    }
    keys = [(f["path"], f["line"], f["target"]) for f in data["findings"]]
    assert keys == [("a.md", 1, "q"), ("a.md", 1, "y.md"), ("b.md", 1, "z.md")]
    assert set(data["findings"][0]) == {
        "check",
        "severity",
        "path",
        "line",
        "target",
        "message",
        "hint",
        "fingerprint",
    }
    assert data["findings"][2]["fingerprint"] == "dead-link|b.md|z.md"


def test_output_is_byte_identical_and_the_tree_is_untouched(tree, capsys):
    root = tree({"a.md": "[x](y.md)", "b/c.md": "[z](../a.md) [q](w.md)"})
    before = snapshot(root)
    outputs = []
    for fmt in ("json", "json", "text", "text"):
        main(["check", "--root", str(root), "--format", fmt])
        outputs.append(capsys.readouterr().out)
    assert outputs[0] == outputs[1] and outputs[2] == outputs[3]
    assert snapshot(root) == before


def test_exit_codes_follow_fail_on(tree, capsys):
    root = tree({"errors/a.md": "[x](gone.md) [y](label)", "candidates/b.md": "[l](label)"})
    both = ["check", "--root", str(root / "errors")]
    soft = ["check", "--root", str(root / "candidates")]
    assert main(both) == 0
    assert main([*both, "--fail-on", "never"]) == 0
    assert main([*both, "--fail-on", "error"]) == 1
    assert main([*soft, "--fail-on", "error"]) == 0
    assert main([*soft, "--fail-on", "warn"]) == 0
    assert main([*soft, "--fail-on", "candidate"]) == 1
    capsys.readouterr()


def test_missing_root_exits_3_with_a_partial_report(tmp_path, capsys):
    code = main(["check", "--root", str(tmp_path / "nope"), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 3
    assert data["scan"]["error"] == "root is not a directory"


def test_usage_errors_exit_2(tree, capsys):
    root = tree({"a.md": "x"})
    for argv in (["--only", "bogus"], ["--fail-on", "x"], ["--format", "xml"]):
        try:
            main(["check", "--root", str(root), *argv])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(argv)
    capsys.readouterr()


def test_text_report_lists_rows_and_caps_them(tree):
    files = {f"n{i}.md": "[x](gone.md)" for i in range(4)}
    text = check(tree(files)).render_text(max_rows=2)
    assert "error     dead-link              4" in text
    assert "== dead-link (error) 4" in text
    assert "n0.md:1  gone.md  target not found" in text
    assert "... 2 more" in text


def test_only_and_skip_select_checks(tree):
    root = tree({"n.md": "<!-- shck: ignore dead-link -->\n[a](g.md)"})
    assert check(root, only={"ignore-without-reason"}).findings[0].check == "ignore-without-reason"
    assert check(root, only={"dead-link"}).findings == []
