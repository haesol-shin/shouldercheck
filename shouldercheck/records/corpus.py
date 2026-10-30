"""All files in scope, parsed once, plus link resolution against the tree on disk."""

import posixpath
import re
from dataclasses import dataclass
from urllib.parse import unquote

from shouldercheck.records import markdown
from shouldercheck.records.config import Config
from shouldercheck.records.scan import Scan

SCHEME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]+:|//|[A-Za-z]:[\\/])")
DATED_SUFFIX = re.compile(r"^(?:v\d+|\d{6,8}|\d{4}-\d{2}-\d{2})\w*$")


@dataclass
class Doc:
    path: str
    text: str
    parsed: markdown.ParsedDoc
    frozen: bool


@dataclass(frozen=True)
class Resolution:
    """kind: skip (external or not resolved by rule), self, file, dir, directory (not
    linkable), missing."""

    kind: str
    path: str = ""


class Corpus:
    def __init__(self, cfg: Config, scan: Scan, docs: dict[str, Doc]) -> None:
        self.cfg = cfg
        self.scan = scan
        self.docs = docs
        self._by_name: dict[str, list[str]] = {}
        for rel in sorted(scan.all_files):
            self._by_name.setdefault(posixpath.basename(rel), []).append(rel)

    def resolve(self, doc_path: str, target: str) -> Resolution:
        """Resolve a link target relative to the file's own folder; no root fallback."""
        if SCHEME.match(target) or target.startswith(("/", "~")):
            return Resolution("skip")
        path = unquote(target.partition("#")[0])
        if not path:
            return Resolution("self", doc_path)
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(doc_path), path))
        if joined == ".." or joined.startswith("../"):
            return Resolution("missing")
        if joined in self.scan.all_files:
            return Resolution("file", joined)
        if joined in self.scan.all_dirs:
            return Resolution("dir" if self.cfg.link_dirs else "directory", joined)
        return Resolution("missing", joined)

    def hint_for(self, target: str) -> str | None:
        """`moved?` for a unique same-name file, `renamed?` for a unique dated or versioned one."""
        path = unquote(target.partition("#")[0])
        name = posixpath.basename(posixpath.normpath(path))
        if not name:
            return None
        same = self._by_name.get(name, [])
        if len(same) == 1:
            return f"moved? {same[0]}"
        stem, ext = posixpath.splitext(name)
        renamed = [
            paths[0]
            for other, paths in self._by_name.items()
            if len(paths) == 1 and self._is_renamed(stem, ext, other)
        ]
        return f"renamed? {renamed[0]}" if len(renamed) == 1 else None

    @staticmethod
    def _is_renamed(stem: str, ext: str, other: str) -> bool:
        other_stem, other_ext = posixpath.splitext(other)
        if other_ext != ext or len(other_stem) <= len(stem) + 1 or not other_stem.startswith(stem):
            return False
        return other_stem[len(stem)] in "-_." and bool(
            DATED_SUFFIX.match(other_stem[len(stem) + 1 :])
        )


def build_corpus(cfg: Config, scan: Scan) -> Corpus:
    docs: dict[str, Doc] = {}
    for rel in scan.paths:
        try:
            text = (scan.root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            scan.skipped.append((rel, "unreadable"))
            continue
        docs[rel] = Doc(rel, text, markdown.parse(text), cfg.frozen(rel))
    scan.skipped.sort()
    return Corpus(cfg, scan, docs)
