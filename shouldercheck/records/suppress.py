"""Sort findings into listed, frozen and suppressed, and flag ignores that lack a reason."""

from collections import Counter
from dataclasses import dataclass, field

from shouldercheck.records.config import Config
from shouldercheck.records.corpus import Corpus
from shouldercheck.records.findings import Finding, clip

IGNORE_CHECK = "ignore-without-reason"


@dataclass
class Partition:
    listed: list[Finding] = field(default_factory=list)
    frozen: Counter[str] = field(default_factory=Counter)
    frozen_paths: dict[str, set[str]] = field(default_factory=dict)
    suppressed: Counter[str] = field(default_factory=Counter)


def reasonless_ignores(corpus: Corpus, cfg: Config) -> list[Finding]:
    severity = cfg.severity(IGNORE_CHECK)
    if severity is None:
        return []
    found = []
    for entry in cfg.ignores:
        if entry.reason is None and cfg.display_path:
            found.append(
                Finding(
                    IGNORE_CHECK,
                    severity,
                    cfg.display_path,
                    "per-path ignore has no reason",
                    target=entry.glob,
                )
            )
    for doc in corpus.docs.values():
        for ignore in doc.parsed.ignores:
            if ignore.reason is None:
                found.append(
                    Finding(
                        IGNORE_CHECK,
                        severity,
                        doc.path,
                        'inline ignore needs reason="..."',
                        line=ignore.line,
                        target=",".join(ignore.checks),
                    )
                )
    return found


def _frozen(finding: Finding, corpus: Corpus) -> bool:
    """A file finding is frozen with its file; a folder finding when all its files are."""
    if finding.path.endswith("/"):
        inside = [d for p, d in corpus.docs.items() if p.startswith(finding.path)]
        return bool(inside) and all(d.frozen for d in inside)
    doc = corpus.docs.get(finding.path)
    return doc is not None and doc.frozen


def _ignored(finding: Finding, corpus: Corpus, cfg: Config) -> bool:
    if finding.check == IGNORE_CHECK:
        return False
    spellings = {finding.path, finding.path.rstrip("/")}
    if any(finding.check in e.checks and any(map(e.matcher, spellings)) for e in cfg.ignores):
        return True
    doc = corpus.docs.get(finding.path)
    if doc is None or finding.line is None:
        return False
    return any(
        finding.check in ig.checks and finding.line in (ig.line, ig.line + 1)
        for ig in doc.parsed.ignores
    )


def _selected(finding: Finding, paths: tuple[str, ...] | None) -> bool:
    """With --paths, keep findings in those files; a folder finding when one is inside it."""
    if paths is None:
        return True
    here = finding.path
    return any(
        not p
        or here == p
        or here.startswith(p + "/")
        or (here.endswith("/") and p.startswith(here))
        for p in paths
    )


def partition(
    findings: list[Finding],
    corpus: Corpus,
    cfg: Config,
    baseline: set[str] | None = None,
    paths: tuple[str, ...] | None = None,
) -> Partition:
    """Order matters: --paths narrows first, so the counts describe the same files."""
    result = Partition()
    for finding in sorted(findings, key=Finding.sort_key):
        if not _selected(finding, paths):
            continue
        if _frozen(finding, corpus):
            result.frozen[finding.check] += 1
            result.frozen_paths.setdefault(finding.check, set()).add(finding.path)
        elif _ignored(finding, corpus, cfg) or clip(finding.fingerprint) in (baseline or ()):
            result.suppressed[finding.check] += 1
        else:
            result.listed.append(finding)
    return result
