from collections.abc import Callable
from pathlib import Path

import pytest

from shouldercheck.memory.find import Result, run_find
from shouldercheck.records.config import Config, load_config


@pytest.fixture(autouse=True)
def private_dirs(tmp_path_factory, monkeypatch):
    """No test reads or writes the user's cache or query log."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path_factory.mktemp("cache")))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("state")))
    monkeypatch.delenv("SHCK_CALLER", raising=False)
    monkeypatch.delenv("SHCK_SESSION", raising=False)


@pytest.fixture
def tree(tmp_path: Path) -> Callable[..., Path]:
    """Build a synthetic record base: tree({"a.md": "text"}) returns its root."""
    base = tmp_path / "base"

    def build(files: dict[str, str]) -> Path:
        for rel, text in files.items():
            path = base / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return base

    return build


def load(root: Path, config: str | None = None) -> Config:
    path = None
    if config is not None:
        path = root / "shck.toml"
        path.write_text(config, encoding="utf-8")
    return load_config(path, root, root)


def find(root: Path, query: str, config: str | None = None, **kwargs) -> Result:
    return run_find(load(root, config), query, **kwargs)


def paths(result: Result) -> list[str]:
    return [hit["path"] for hit in result.hits]
