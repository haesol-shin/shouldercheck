"""orphan: a file, or a folder of files, that no other file links to."""

import os
import posixpath
import time
from collections import defaultdict

from shouldercheck.records.corpus import Corpus, Doc
from shouldercheck.records.findings import Finding

DAY = 86400


def inbound_sources(corpus: Corpus) -> dict[str, set[str]]:
    """Target path -> files that reference it, in every enabled link style."""
    sources: dict[str, set[str]] = defaultdict(set)
    for doc in corpus.docs.values():
        for ref in corpus.refs(doc):
            if ref.resolution.kind == "file" and ref.resolution.path != doc.path:
                sources[ref.resolution.path].add(doc.path)
    return sources


def _in_scope(corpus: Corpus, doc: Doc) -> bool:
    opts = corpus.cfg.orphans
    if not opts.scope(doc.path) or opts.exempt(doc.path):
        return False
    if opts.exempt_names(posixpath.basename(doc.path)):
        return False
    if opts.grace_days:
        age = time.time() - os.stat(corpus.scan.root / doc.path).st_mtime
        return age >= opts.grace_days * DAY
    return True


def _folder(path: str, depth: int) -> str | None:
    """First `depth` folders of the path; a file with fewer folders is its own unit."""
    parts = [part for part in posixpath.dirname(path).split("/") if part]
    return "/".join(parts[:depth]) if len(parts) >= depth else None


def _reached(
    corpus: Corpus, docs: list[Doc], sources: dict[str, set[str]], inside: str | None
) -> tuple[bool, bool]:
    """(real, catalog-only) inbound found for a unit; sources inside the folder do not count."""
    catalog = corpus.cfg.orphans.catalog
    real = cataloged = False
    for doc in docs:
        for source in sources.get(doc.path, ()):
            if inside and source.startswith(inside):
                continue
            if catalog(source):
                cataloged = True
            else:
                real = True
    return real, cataloged


def run(corpus: Corpus) -> list[Finding]:
    severity = corpus.cfg.severity("orphan")
    opts = corpus.cfg.orphans
    if severity is None or not opts.scope:
        return []
    sources = inbound_sources(corpus)
    units: dict[str, list[Doc]] = defaultdict(list)
    for doc in corpus.docs.values():
        if _in_scope(corpus, doc):
            folder = _folder(doc.path, opts.folder_depth) if opts.unit == "folder" else None
            units[folder + "/" if folder else doc.path].append(doc)
    findings = []
    for key, docs in sorted(units.items()):
        is_folder = key.endswith("/")
        real, cataloged = _reached(corpus, docs, sources, key if is_folder else None)
        if real:
            continue
        where = "from outside the folder" if is_folder else "link"
        size = f" ({len(docs)} files)" if is_folder else ""
        if cataloged:
            findings.append(
                Finding("orphan", "candidate", key, f"only linked from a catalog{size}")
            )
        else:
            findings.append(Finding("orphan", severity, key, f"no inbound {where}{size}"))
    return findings
