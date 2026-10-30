import tomllib
from pathlib import Path

import pytest

import shouldercheck
from shouldercheck.cli import main


def test_package_version_matches_pyproject():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert shouldercheck.__version__ == pyproject["project"]["version"]


def test_cli_prints_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"shck {shouldercheck.__version__}"
