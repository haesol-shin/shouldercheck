from tests.records.conftest import check, rows

RULE = '[[fields.rules]]\nmatch = ["projects/*.md"]\nrequire = ["status"]\n'


def fields(root, config):
    return [(p, t) for _, p, _, t in rows(check(root, config), "missing-field")]


def test_front_matter_versus_head_line_versus_nothing(tree):
    root = tree(
        {
            "projects/a.md": "---\nstatus: active\n---\n",
            "projects/b.md": "# B\nstatus: active · updated: 2026-10-20\n",
            "projects/c.md": "# C\nno field here\n",
            "projects/sub/d.md": "# not matched by projects/*.md\n",
        }
    )
    assert fields(root, RULE) == [("projects/b.md", "status"), ("projects/c.md", "status")]
    assert fields(root, RULE + "body_lines = true\n") == [("projects/c.md", "status")]


def test_head_line_must_be_near_the_top(tree):
    root = tree({"projects/a.md": "\n" * 5 + "status: active\n"})
    on = RULE + "body_lines = true\nbody_lines_max = 3\n"
    assert fields(root, on) == [("projects/a.md", "status")]
    assert fields(root, RULE + "body_lines = true\n") == []


def test_values_are_compared_after_normalisation(tree):
    root = tree(
        {
            "projects/ok.md": "---\nstatus: Active · updated: 2026-10-20\n---\n",
            "projects/ok2.md": "---\nstatus: hold (until May)\n---\n",
            "projects/bad.md": "---\nstatus: maybe\n---\n",
        }
    )
    toml = RULE + 'values = { status = ["active", "hold", "done"] }\n'
    report = check(root, toml)
    assert [(f.path, f.message) for f in report.findings] == [
        ("projects/bad.md", "value of status is 'maybe', expected one of: active, hold, done")
    ]
    assert report.findings[0].severity == "warn"


def test_empty_value_counts_as_missing(tree):
    root = tree({"projects/a.md": "---\nstatus:\n---\n"})
    assert fields(root, RULE) == [("projects/a.md", "status")]


FOLDER = (
    "[[fields.rules]]\n"
    'folder_any = { in = ["jobs/*"], when_present = ["result*.md", "design*.md"] }\n'
    'require = ["owner"]\n'
)


def test_folder_rule_applies_only_where_a_result_is_present(tree):
    root = tree(
        {
            "jobs/a/intent.md": "x",
            "jobs/a/result.md": "---\nowner: me\n---\n",
            "jobs/b/intent.md": "---\nowner: me\n---\n",
            "jobs/b/design-v1.md": "x",
            "jobs/c/intent.md": "x",
            "jobs/c/spec.md": "x",
            "jobs/d/result.md": "x",
            "jobs/d/deeper/result.md": "x",
        }
    )
    got = check(root, FOLDER).findings
    assert [(f.path, f.target) for f in got] == [("jobs/d/", "owner")]
    assert got[0].message == "no file in the folder has a valid field: owner"


def test_rule_without_a_selector_or_with_two_is_a_config_error(tree):
    import pytest

    from shouldercheck.records.config import ConfigError
    from tests.records.conftest import load

    root = tree({})
    for toml in (
        '[[fields.rules]]\nrequire = ["a"]\n',
        '[[fields.rules]]\nmatch = ["a"]\nfolder_any = { in = ["b"] }\nrequire = ["a"]\n',
        '[[fields.rules]]\nmatch = ["a"]\nrequire = []\n',
    ):
        with pytest.raises(ConfigError):
            load(root, toml)
