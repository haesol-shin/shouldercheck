"""missing-field: required front matter keys, with a fallback to `key: value` lines in the head."""

import posixpath
import re
from collections import defaultdict

from shouldercheck.records.config import FieldRule
from shouldercheck.records.corpus import Corpus, Doc
from shouldercheck.records.findings import Finding

FIRST_TOKEN = re.compile(r"[\s(·]")


def normalize(value: str) -> str:
    """`active · updated: 2026-10-20` and `active (since May)` both mean `active`."""
    return FIRST_TOKEN.split(value.strip(), maxsplit=1)[0].casefold()


def lookup(doc: Doc, key: str, body_lines: bool, body_max: int) -> list[str]:
    """Values of a key from front matter, else from the first lines of the body."""
    wanted = key.casefold()
    for name, value in doc.parsed.front.items():
        if name.casefold() == wanted:
            items = value if isinstance(value, list) else [value]
            return [item for item in items if item]
    if body_lines:
        head = doc.parsed.head_fields
        values = [f.value for f in head if f.key.casefold() == wanted and f.offset < body_max]
        return [value for value in values if value][:1]
    return []


def _problem(doc: Doc, key: str, rule: FieldRule) -> str | None:
    """Why the document fails the rule for this key; None when it passes."""
    found = lookup(doc, key, rule.body_lines, rule.body_lines_max)
    if not found:
        return f"missing field: {key}"
    allowed = rule.values.get(key)
    if allowed is not None and not any(
        normalize(v) in {a.casefold() for a in allowed} for v in found
    ):
        return f"value of {key} is {normalize(found[0])!r}, expected one of: {', '.join(allowed)}"
    return None


def _file_rule(corpus: Corpus, rule: FieldRule, severity: str) -> list[Finding]:
    findings = []
    for doc in corpus.docs.values():
        if not rule.match(doc.path):
            continue
        for key in rule.require:
            problem = _problem(doc, key, rule)
            if problem:
                findings.append(Finding("missing-field", severity, doc.path, problem, target=key))
    return findings


def _folder_rule(corpus: Corpus, rule: FieldRule, severity: str) -> list[Finding]:
    folders: dict[str, list[Doc]] = defaultdict(list)
    for doc in corpus.docs.values():
        folders[posixpath.dirname(doc.path)].append(doc)
    findings = []
    for folder, docs in sorted(folders.items()):
        if not folder or not (rule.folder_in and rule.folder_in(folder)):
            continue
        if rule.when_present and not any(
            rule.when_present(posixpath.basename(d.path)) for d in docs
        ):
            continue
        for key in rule.require:
            if all(_problem(doc, key, rule) for doc in docs):
                message = f"no file in the folder has a valid field: {key}"
                findings.append(
                    Finding("missing-field", severity, folder + "/", message, target=key)
                )
    return findings


def run(corpus: Corpus) -> list[Finding]:
    severity = corpus.cfg.severity("missing-field")
    if severity is None:
        return []
    findings: list[Finding] = []
    for rule in corpus.cfg.field_rules:
        if rule.folder_in is None:
            findings += _file_rule(corpus, rule, severity)
        else:
            findings += _folder_rule(corpus, rule, severity)
    return list(dict.fromkeys(findings))
