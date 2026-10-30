"""stale: files whose own `updated:` date is older than a limit.

The date is the owner's claim, not a measure of truth. Nobody is notified.
"""

import datetime
import re

from shouldercheck.records.checks.missing_field import lookup
from shouldercheck.records.corpus import Corpus
from shouldercheck.records.findings import Finding

DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
HEAD_LINES = 12


def _today() -> datetime.date:
    return datetime.date.today()


def _updated(corpus: Corpus, path: str) -> datetime.date | None:
    doc = corpus.docs[path]
    for value in lookup(doc, corpus.cfg.stale.field, True, HEAD_LINES):
        match = DATE.search(value)
        if match:
            try:
                return datetime.date(*map(int, match.groups()))
            except ValueError:
                return None
    return None


def run(corpus: Corpus) -> list[Finding]:
    severity = corpus.cfg.severity("stale")
    opts = corpus.cfg.stale
    if severity is None or not opts.match:
        return []
    today = _today()
    findings = []
    for path in corpus.docs:
        updated = _updated(corpus, path) if opts.match(path) else None
        if updated is None or (today - updated).days <= opts.days:
            continue
        message = f"{opts.field} {updated} is {(today - updated).days} days old (limit {opts.days})"
        findings.append(Finding("stale", severity, path, message))
    return findings
