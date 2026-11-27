"""size: documents, lines and maps that are too long to read or to load into a prompt.

Characters are counted, not bytes or words: Korean text takes three bytes per character and
whitespace-separated words undercount CJK.
"""

from shouldercheck.records.corpus import Corpus, Doc
from shouldercheck.records.findings import Finding
from shouldercheck.records.markdown import split_lines


def _document(doc: Doc, corpus: Corpus, primary: str) -> list[Finding]:
    opts = corpus.cfg.size
    chars = len(doc.text)
    if chars > opts.high_chars:
        return [
            Finding(
                "size",
                primary,
                doc.path,
                f"{chars} characters (over {opts.high_chars})",
                target="chars",
            )
        ]
    if chars > opts.warn_chars:
        return [
            Finding(
                "size",
                "candidate",
                doc.path,
                f"{chars} characters (over {opts.warn_chars})",
                target="chars",
            )
        ]
    return []


def _longest_line(doc: Doc, corpus: Corpus, primary: str) -> list[Finding]:
    limit = corpus.cfg.size.max_line_chars
    lengths = [len(line) for line in split_lines(doc.text)]
    longest = max(lengths, default=0)
    if longest <= limit:
        return []
    message = f"line of {longest} characters (over {limit}); {sum(n > limit for n in lengths)} long"
    return [Finding("size", primary, doc.path, message, lengths.index(longest) + 1, "line-length")]


def _long_lines(doc: Doc, corpus: Corpus, primary: str) -> list[Finding]:
    limit = corpus.cfg.size.line_chars
    return [
        Finding(
            "size",
            primary,
            doc.path,
            f"line of {len(line)} characters (over {limit})",
            n,
            "line-chars",
        )
        for n, line in enumerate(split_lines(doc.text), 1)
        if len(line) > limit
    ]


def _lines(doc: Doc, corpus: Corpus, primary: str) -> list[Finding]:
    """`line_chars` names every long line and replaces the one-row `max_line_chars` summary."""
    if corpus.cfg.size.line_chars is None:
        return _longest_line(doc, corpus, primary)
    return _long_lines(doc, corpus, primary)


def _map(doc: Doc, corpus: Corpus) -> list[Finding]:
    opts = corpus.cfg.size
    if not opts.maps(doc.path) or len(doc.text) <= opts.map_budget_chars:
        return []
    message = f"map of {len(doc.text)} characters (budget {opts.map_budget_chars})"
    return [Finding("size", "candidate", doc.path, message, target="map-budget")]


def run(corpus: Corpus) -> list[Finding]:
    primary = corpus.cfg.severity("size")
    if primary is None:
        return []
    findings = []
    for doc in corpus.docs.values():
        if corpus.cfg.size.exclude(doc.path):
            continue
        findings += _document(doc, corpus, primary)
        findings += _lines(doc, corpus, primary)
        findings += _map(doc, corpus)
    return findings
