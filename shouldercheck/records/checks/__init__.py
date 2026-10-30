"""One module per check: `run(corpus) -> list[Finding]`."""

from collections.abc import Callable

from shouldercheck.records.checks import (
    alias_dup,
    dead_anchor,
    dead_link,
    dup_content,
    missing_field,
    orphan,
    size,
    stale,
)
from shouldercheck.records.corpus import Corpus
from shouldercheck.records.findings import Finding

CHECKS: dict[str, Callable[[Corpus], list[Finding]]] = {
    "dead-link": dead_link.run,
    "dead-anchor": dead_anchor.run,
    "orphan": orphan.run,
    "missing-field": missing_field.run,
    "alias-dup": alias_dup.run,
    "size": size.run,
    "dup-content": dup_content.run,
    "stale": stale.run,
}
