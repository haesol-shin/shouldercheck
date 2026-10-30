"""alias-dup: one alias claimed by two documents makes a link to it ambiguous."""

import posixpath
import re
from collections import defaultdict

from shouldercheck.records.anchors import plain
from shouldercheck.records.corpus import Corpus, Doc
from shouldercheck.records.findings import Finding

IGNORED_CHARS = re.compile(r"[\s\-._·]")


def normalize(alias: str) -> str:
    return IGNORED_CHARS.sub("", alias.casefold())


def _aliases(doc: Doc) -> list[str]:
    value = doc.parsed.front.get("aliases", [])
    items = value if isinstance(value, list) else value.split(",")
    return [item.strip() for item in items if item.strip()]


def _names(doc: Doc) -> set[str]:
    """Normalised stem and title: what another document's alias may collide with."""
    names = {normalize(posixpath.splitext(posixpath.basename(doc.path))[0])}
    title = doc.parsed.front.get("title")
    if isinstance(title, str) and title:
        names.add(normalize(title))
    elif doc.parsed.headings:
        names.add(normalize(plain(doc.parsed.headings[0].text)))
    names.discard("")
    return names


def run(corpus: Corpus) -> list[Finding]:
    severity = corpus.cfg.severity("alias-dup")
    if severity is None:
        return []
    # Evaluation and snapshot copies repeat the originals, so frozen files own no alias.
    docs = [doc for doc in corpus.docs.values() if not doc.frozen]
    owners: dict[str, list[tuple[str, str]]] = defaultdict(list)
    names: dict[str, set[str]] = defaultdict(set)
    for doc in docs:
        for alias in _aliases(doc):
            owners[normalize(alias)].append((doc.path, alias))
        for name in _names(doc):
            names[name].add(doc.path)
    findings = []
    for key, claims in sorted(owners.items()):
        paths = sorted({path for path, _ in claims})
        for path, alias in claims:
            line = corpus.docs[path].parsed.front_lines.get("aliases")
            others = [p for p in paths if p != path]
            if others:
                message = f"alias also used by: {', '.join(others[:3])}"
                findings.append(Finding("alias-dup", severity, path, message, line, alias))
                continue
            named = sorted(names.get(key, set()) - {path})
            if named:
                message = f"alias equals the title or stem of: {', '.join(named[:3])}"
                findings.append(Finding("alias-dup", "candidate", path, message, line, alias))
    return list(dict.fromkeys(findings))
