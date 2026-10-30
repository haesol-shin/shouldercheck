"""Walk a record base read-only and decide which files are in scope."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from shouldercheck.records.config import Config


@dataclass
class Scan:
    root: Path
    paths: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    all_files: set[str] = field(default_factory=set)
    all_dirs: set[str] = field(default_factory=set)


def scan_tree(cfg: Config) -> Scan:
    """List files under the root. Symlinks are never followed; in-scope ones are skipped."""
    scan = Scan(cfg.root)

    def on_error(exc: OSError) -> None:
        name = exc.filename
        rel = os.path.relpath(name, cfg.root).replace(os.sep, "/") if name else "."
        scan.skipped.append((rel, "unreadable"))

    for folder, dirnames, filenames in os.walk(cfg.root, onerror=on_error):
        dirnames[:] = sorted(
            d for d in dirnames if d != ".git" and not os.path.islink(os.path.join(folder, d))
        )
        rel_folder = os.path.relpath(folder, cfg.root).replace(os.sep, "/")
        prefix = "" if rel_folder == "." else rel_folder + "/"
        if prefix:
            scan.all_dirs.add(rel_folder)
        for name in sorted(filenames):
            _visit(cfg, scan, os.path.join(folder, name), prefix + name)
    scan.paths.sort()
    scan.skipped.sort()
    return scan


def _visit(cfg: Config, scan: Scan, full: str, rel: str) -> None:
    in_scope = cfg.include(rel) and not cfg.exclude(rel)
    if os.path.islink(full):
        if in_scope:
            scan.skipped.append((rel, "symlink"))
        return
    scan.all_files.add(rel)
    if not in_scope:
        return
    try:
        size = os.stat(full).st_size
    except OSError:
        scan.skipped.append((rel, "unreadable"))
        return
    if size > cfg.max_read_chars:
        scan.skipped.append((rel, "too-large"))
        return
    scan.paths.append(rel)
