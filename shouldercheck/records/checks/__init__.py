"""One module per check: `run(corpus) -> list[Finding]`."""

from collections.abc import Callable

from shouldercheck.records.checks import dead_anchor, dead_link, orphan
from shouldercheck.records.corpus import Corpus
from shouldercheck.records.findings import Finding

CHECKS: dict[str, Callable[[Corpus], list[Finding]]] = {
    "dead-link": dead_link.run,
    "dead-anchor": dead_anchor.run,
    "orphan": orphan.run,
}
