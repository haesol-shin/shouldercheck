import pytest

from shouldercheck.cli import main
from shouldercheck.records.config import ConfigError, load_config
from tests.records.conftest import check, rows


def test_unknown_key_exits_2(tree, capsys):
    root = tree({"shck.toml": "[checks]\nbogus = 'error'\n"})
    assert main(["check", "--root", str(root)]) == 2
    assert "bogus" in capsys.readouterr().err


@pytest.mark.parametrize(
    "toml",
    [
        "surprise = 1\n",
        'exclude = ["[z-a]"]\n',
        "[checks]\ndead-link = 'loud'\n",
        "version = 2\n",
        "[[per-path-ignores]]\nglob = 'a'\nchecks = ['nope']\n",
        "[[per-path-ignores]]\nglob = 'a'\nchecks = ['dead-link']\nwhy = 'x'\n",
        "fail_on = 'sometimes'\n",
    ],
)
def test_invalid_profile_is_a_config_error(tree, toml):
    root = tree({"shck.toml": toml})
    with pytest.raises(ConfigError):
        load_config(None, root, root)


def test_discovery_goes_up_and_prefers_shck_toml(tree):
    root = tree({"shck.toml": 'exclude = ["skip/**"]\n', ".shck.toml": "", "a/b/n.md": "x"})
    cfg = load_config(None, None, root / "a" / "b")
    assert cfg.path == root / "shck.toml"
    assert cfg.root == root


def test_explicit_config_wins_and_missing_file_is_an_error(tree):
    root = tree({"shck.toml": "", "other.toml": 'include = ["x.md"]\n'})
    assert load_config(root / "other.toml", None, root).path == root / "other.toml"
    with pytest.raises(ConfigError):
        load_config(root / "none.toml", None, root)


def test_built_in_profile_scans_markdown_and_skips_hidden_and_conflicts(tree):
    root = tree(
        {
            "a.md": "[x](gone.md)",
            ".h/b.md": "[x](gone.md)",
            "c (sfconflict).md": "[x](gone.md)",
            "d.txt": "[x](gone.md)",
        }
    )
    report = check(root)
    assert report.config is None
    assert rows(report, "dead-link") == [("error", "a.md", 1, "gone.md")]


def test_config_include_and_exclude(tree):
    root = tree({"a/x.md": "[x](gone.md)", "b/y.md": "[x](gone.md)", "b/z.md": "[x](gone.md)"})
    toml = 'include = ["b/**/*.md"]\nexclude = ["b/z.md"]\n'
    assert [p for _, p, _, _ in rows(check(root, toml), "dead-link")] == ["b/y.md"]


def test_check_can_be_turned_off(tree):
    root = tree({"a.md": "[x](gone.md)"})
    assert check(root, '[checks]\ndead-link = "off"\n').findings == []
