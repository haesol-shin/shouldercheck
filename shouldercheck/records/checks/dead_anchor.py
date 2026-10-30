"""dead-anchor: a link to a heading that the target file does not have."""

from shouldercheck.records.anchors import has_fragment
from shouldercheck.records.corpus import Corpus
from shouldercheck.records.findings import Finding


def run(corpus: Corpus) -> list[Finding]:
    severity = corpus.cfg.severity("dead-anchor")
    if severity is None:
        return []
    opts = corpus.cfg.opts
    findings = []
    for doc in corpus.docs.values():
        for ref in corpus.refs(doc):
            if ref.fragment is None or ref.resolution.kind not in ("file", "self"):
                continue
            ids = corpus.anchor_ids(ref.resolution.path)
            if ids is None or has_fragment(ref.fragment, ids, opts):
                continue
            findings.append(
                Finding("dead-anchor", severity, doc.path, "anchor not found", ref.line, ref.target)
            )
    return findings
