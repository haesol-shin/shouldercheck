"""dead-link: a reference whose target does not exist."""

from shouldercheck.records.corpus import Corpus, Ref
from shouldercheck.records.findings import Finding

MESSAGES = {"missing": "target not found", "directory": "target is a directory"}


def _finding(corpus: Corpus, path: str, ref: Ref, primary: str) -> Finding | None:
    kind = ref.resolution.kind
    if ref.style == "backtick":
        # Backticks name commands and other repositories' files; a miss is rarely a defect.
        if kind != "missing" or not corpus.cfg.opts.backtick_dead:
            return None
        return Finding(
            "dead-link", "candidate", path, "backtick path not found", ref.line, ref.target
        )
    if ref.style == "wiki" and kind == "ambiguous":
        names = ", ".join(ref.resolution.candidates[:3])
        return Finding(
            "dead-link", "candidate", path, "ambiguous wiki target", ref.line, ref.target, names
        )
    if kind not in MESSAGES:
        return None
    if ref.label_like:
        return Finding("dead-link", "candidate", path, "label-like target", ref.line, ref.target)
    hint = corpus.hint_for(ref.target) if ref.style == "markdown" else None
    return Finding("dead-link", primary, path, MESSAGES[kind], ref.line, ref.target, hint)


def run(corpus: Corpus) -> list[Finding]:
    primary = corpus.cfg.severity("dead-link")
    if primary is None:
        return []
    findings = []
    for doc in corpus.docs.values():
        for ref in corpus.refs(doc):
            finding = _finding(corpus, doc.path, ref, primary)
            if finding:
                findings.append(finding)
    return findings
