import json

from shouldercheck.cli import main
from tests.records.conftest import check, rows


def run(argv, capsys):
    code = main(["check", "--format", "json", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_baseline_mutes_known_findings_even_after_the_line_moves(tree, tmp_path, capsys):
    root = tree({"n.md": "[x](gone.md)\n"})
    _, first = run(["--root", str(root)], capsys)
    baseline = tmp_path / "base.json"
    baseline.write_text(json.dumps(first), encoding="utf-8")
    (root / "n.md").write_text("added line\n\n[x](gone.md) [y](new.md)\n", encoding="utf-8")
    _, second = run(["--root", str(root), "--baseline", str(baseline)], capsys)
    assert [f["target"] for f in second["findings"]] == ["new.md"]
    assert second["summary"]["suppressed"] == 1
    assert second["summary"]["by_check"]["dead-link"]["suppressed"] == 1


def test_unusable_baseline_is_a_usage_error(tree, tmp_path, capsys):
    root = tree({"n.md": "x"})
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert main(["check", "--root", str(root), "--baseline", str(bad)]) == 2
    assert main(["check", "--root", str(root), "--baseline", str(tmp_path / "none.json")]) == 2
    capsys.readouterr()


def test_paths_limit_the_listing_but_not_the_graph(tree, capsys):
    root = tree(
        {
            "a.md": "[x](gone.md)",
            "d/b.md": "[x](gone.md)",
            "d/c.md": "[x](gone.md)",
            "notes/p.md": "x",
            "notes/q.md": "x",
            "z.md": "[p](notes/p.md)",
        }
    )
    (root / "shck.toml").write_text('[orphans]\nscope = ["notes/**"]\n', encoding="utf-8")
    base = ["--root", str(root)]
    _, got = run([*base, "--paths", "d/b.md"], capsys)
    assert [f["path"] for f in got["findings"]] == ["d/b.md"]
    _, got = run([*base, "--paths", "d"], capsys)
    assert [f["path"] for f in got["findings"]] == ["d/b.md", "d/c.md"]
    _, got = run([*base, "--paths", str(root / "notes/p.md"), "notes/q.md"], capsys)
    # p.md is linked from the unselected z.md, so only q.md is an orphan.
    assert [f["path"] for f in got["findings"]] == ["notes/q.md"]


def test_paths_work_with_the_library_too(tree):
    root = tree({"a.md": "[x](gone.md)", "b.md": "[x](gone.md)"})
    report = check(root, paths=("b.md",))
    assert rows(report, "dead-link") == [("error", "b.md", 1, "gone.md")]
