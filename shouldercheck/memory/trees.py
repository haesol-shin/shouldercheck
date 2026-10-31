"""Open the index of the live tree or of a git snapshot, once per distinct tree."""

import dataclasses
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from shouldercheck.memory import snapshot
from shouldercheck.memory.find import Index, open_index
from shouldercheck.memory.rank import Ranker
from shouldercheck.memory.settings import RECORDS, FindSettings, resolve_dir
from shouldercheck.memory.store import Store, default_cache_dir
from shouldercheck.records.config import Config, ConfigError

LIVE = "live"


@dataclass
class Trees:
    """Indexes opened on demand: the live tree once, each distinct snapshot tree once."""

    cfg: Config
    settings: FindSettings
    git_dir: Path | None
    opened: dict[str, Index] = field(default_factory=dict)
    commits: dict[str, str | None] = field(default_factory=dict)

    def open(self, commit: str | None) -> tuple[Index, str]:
        """The index of the live tree (commit None) or of the tree of `commit`."""
        if commit is None:
            key = LIVE
            if key not in self.opened:
                self.opened[key] = open_index(self.cfg, self.settings)
        else:
            key = snapshot.tree_hash(self._repository(), commit)
            if key not in self.opened:
                self.opened[key] = self._snapshot_index(key, commit)
        self.commits.setdefault(key, commit)
        return self.opened[key], key

    def _repository(self) -> Path:
        if self.git_dir is None:
            raise ConfigError("snapshots need --git-dir or [eval] git_dir")
        return self.git_dir

    def _snapshot_index(self, tree: str, commit: str) -> Index:
        folder = resolve_dir(self.settings.cache_dir, self.cfg, default_cache_dir(self.cfg.root))
        cache_file = folder / f"snap-{tree}.sqlite"
        try:
            store = Store.on_disk(cache_file)
        except Exception:
            store = None
        if store is not None and store.matches(self.cfg):
            ranker = Ranker(store, self.settings)
            return Index(self.cfg, self.settings, store, ranker, "warm", 0, ranker.count(RECORDS))
        if store is not None:
            store.close()
        scratch = Path(tempfile.mkdtemp(prefix="shck-snapshot-"))
        try:
            snapshot.extract(self._repository(), commit, scratch)
            return open_index(
                dataclasses.replace(self.cfg, root=scratch), self.settings, cache_file=cache_file
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def read(self, commit: str | None, rel: str) -> str | None:
        """One file as it is in the live tree or in the snapshot; None when it is absent."""
        if commit is None:
            try:
                return (self.cfg.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        return snapshot.read_file(self._repository(), commit, rel)

    def info(self) -> list[dict]:
        return [
            {"tree": key, "commit": self.commits.get(key), "docs": index.docs}
            for key, index in self.opened.items()
        ]

    def close(self) -> None:
        for index in self.opened.values():
            index.close()
