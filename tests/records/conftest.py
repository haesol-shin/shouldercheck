from collections.abc import Callable
from pathlib import Path

import pytest

from shouldercheck.records.config import Config, load_config
from shouldercheck.records.report import Report, run_check


@pytest.fixture
def tree(tmp_path: Path) -> Callable[..., Path]:
    """Build a synthetic record base: tree({"a.md": "text"}) returns its root."""

    def build(files: dict[str, str]) -> Path:
        for rel, text in files.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return tmp_path

    return build


def load(root: Path, config: str | None = None) -> Config:
    path = None
    if config is not None:
        path = root / "shck.toml"
        path.write_text(config, encoding="utf-8")
    return load_config(path, root, root)


def check(root: Path, config: str | None = None, **kwargs) -> Report:
    return run_check(load(root, config), **kwargs)


def rows(report: Report, name: str) -> list[tuple[str, str, int | None, str | None]]:
    return [(f.severity, f.path, f.line, f.target) for f in report.findings if f.check == name]
