"""dead-link: an inline link whose target does not exist on disk."""

import posixpath
import re

from shouldercheck.records.corpus import Corpus
from shouldercheck.records.findings import Finding
from shouldercheck.records.markdown import Link

EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
MESSAGES = {"missing": "target not found", "directory": "target is a directory"}


def is_label_like(link: Link) -> bool:
    """A parenthetical remark that parsed as a link, not a path: no slash, no extension."""
    path = link.target.partition("#")[0]
    if not link.angled and any(char.isspace() for char in link.target):
        return True
    return "/" not in path and not EXTENSION.search(posixpath.basename(path))


def run(corpus: Corpus) -> list[Finding]:
    primary = corpus.cfg.severity("dead-link")
    if primary is None:
        return []
    findings = []
    for doc in corpus.docs.values():
        for link in doc.parsed.links:
            res = corpus.resolve(doc.path, link.target)
            if res.kind not in MESSAGES:
                continue
            label = is_label_like(link)
            findings.append(
                Finding(
                    "dead-link",
                    "candidate" if label else primary,
                    doc.path,
                    "label-like target" if label else MESSAGES[res.kind],
                    line=link.line,
                    target=link.target,
                    hint=None if label else corpus.hint_for(link.target),
                )
            )
    return findings
