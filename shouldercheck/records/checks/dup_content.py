"""dup-content: files with identical bytes. The survivor is a human choice."""

import hashlib
from collections import defaultdict

from shouldercheck.records.corpus import Corpus
from shouldercheck.records.findings import Finding

MIN_BYTES = 200


def run(corpus: Corpus) -> list[Finding]:
    severity = corpus.cfg.severity("dup-content")
    if severity is None:
        return []
    groups: dict[str, list[str]] = defaultdict(list)
    for doc in corpus.docs.values():
        raw = doc.text.encode("utf-8")
        if len(raw) > MIN_BYTES:
            groups[hashlib.sha256(raw).hexdigest()].append(doc.path)
    findings = []
    for digest, paths in sorted(groups.items()):
        if len(paths) < 2:
            continue
        for path in paths:
            others = ", ".join(p for p in paths if p != path)
            findings.append(
                Finding(
                    "dup-content", severity, path, f"identical to: {others}", target=digest[:12]
                )
            )
    return findings
