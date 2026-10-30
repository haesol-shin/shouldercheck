"""Frozen manifests: files that list other files by relative path, e.g. `hashes.json`."""

import json
import posixpath
import re
from dataclasses import dataclass, field

from shouldercheck.records.config import Config
from shouldercheck.records.scan import Scan

HEX_DIGEST = re.compile(r"^[0-9A-Fa-f]{32,}$")


@dataclass
class Manifests:
    paths: set[str] = field(default_factory=set)
    blocked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def covers(self, rel: str) -> bool:
        return rel in self.paths or any(rel.startswith(prefix) for prefix in self.blocked)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for key, item in value.items() for s in [str(key), *_strings(item)]]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _listed(rel: str, text: str) -> list[str]:
    if rel.lower().endswith(".json"):
        return _strings(json.loads(text))
    names = []
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and HEX_DIGEST.match(parts[0]):
            names.append(parts[1].lstrip("*").strip())
        elif len(parts) == 1 and not line.lstrip().startswith("#"):
            names.append(parts[0])
    return names


def read_manifests(cfg: Config, scan: Scan) -> Manifests:
    """Collect the files each manifest lists; an unreadable one freezes its whole folder."""
    found = Manifests()
    if not cfg.frozen_manifests:
        return found
    for rel in sorted(scan.all_files):
        if not cfg.frozen_manifests(posixpath.basename(rel)):
            continue
        folder = posixpath.dirname(rel)
        try:
            raw = (scan.root / rel).read_bytes()
            if len(raw) > cfg.max_read_chars:
                raise ValueError("too large")
            names = _listed(rel, raw.decode("utf-8"))
        except (OSError, ValueError):
            found.blocked.append(folder + "/" if folder else "")
            found.errors.append(f"unreadable manifest: {rel}")
            continue
        for name in names:
            joined = posixpath.normpath(posixpath.join(folder, name))
            if not name.startswith("/") and not joined.startswith(".."):
                found.paths.add(joined)
    return found
