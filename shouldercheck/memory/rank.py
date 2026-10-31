"""BM25 over weighted fields, a coverage factor, a superseded factor and the exact-name order."""

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from shouldercheck.memory.settings import RECORDS, FindSettings
from shouldercheck.memory.store import DocRow, Store
from shouldercheck.memory.tokens import norm, tokenize

NO_NAME = 3


@dataclass(frozen=True)
class Ranked:
    doc: DocRow
    score: float
    superseded: bool
    replaced_by: tuple[str, ...]
    name_tier: int


class Ranker:
    """Scores one query against an index. Each tier has its own statistics, so scores of
    different tiers are never compared."""

    def __init__(self, store: Store, settings: FindSettings) -> None:
        self.store = store
        self.settings = settings
        self._stats: dict[str, tuple[int, float]] | None = None
        self._replaced: dict[str, set[str]] | None = None

    def tier_names(self) -> list[str]:
        return sorted({doc.tier for doc in self.store.docs().values()})

    def count(self, tier: str = RECORDS) -> int:
        return self._tier_stats().get(tier, (0, 0.0))[0]

    def _tier_stats(self) -> dict[str, tuple[int, float]]:
        if self._stats is None:
            total: dict[str, list[int]] = defaultdict(list)
            for doc in self.store.docs().values():
                total[doc.tier].append(doc.length)
            self._stats = {
                tier: (len(lengths), sum(lengths) / len(lengths) or 1.0)
                for tier, lengths in total.items()
            }
        return self._stats

    def _replacements(self) -> dict[str, set[str]]:
        if self._replaced is None:
            rel = self.settings.relations
            by = rel.words_of("superseded_by")
            of = rel.words_of("supersedes")
            replaced: dict[str, set[str]] = defaultdict(set)
            for src, word, dst in self.store.link_rows([*by, *of]):
                if word in by:
                    replaced[src].add(dst)
                if word in of:
                    replaced[dst].add(src)
            self._replaced = replaced
        return self._replaced

    def rank(self, query: str, tiers: Iterable[str] | None = None) -> dict[str, list[Ranked]]:
        """Every document with a positive score, best first, grouped by tier."""
        terms = sorted(set(tokenize(query)))
        wanted = set(tiers) if tiers is not None else None
        if not terms:
            return {}
        scores = self._score(terms, wanted)
        by_tier: dict[str, list[Ranked]] = defaultdict(list)
        names = self._name_tiers(query, scores)
        for doc_id, score in scores.items():
            doc = self.store.docs()[doc_id]
            by_tier[doc.tier].append(self._ranked(doc, score, names.get(doc_id, NO_NAME)))
        return {tier: self._order(tier, items) for tier, items in by_tier.items()}

    def _score(self, terms: list[str], wanted: set[str] | None) -> dict[int, float]:
        docs = self.store.docs()
        stats = self._tier_stats()
        s = self.settings
        sums: dict[int, float] = defaultdict(float)
        matched: dict[int, int] = defaultdict(int)
        for term in terms:
            rows = [(d, tf) for d, tf in self.store.postings(term) if d in docs]
            df: dict[str, int] = defaultdict(int)
            for doc_id, _ in rows:
                df[docs[doc_id].tier] += 1
            for doc_id, tf in rows:
                doc = docs[doc_id]
                if wanted is not None and doc.tier not in wanted:
                    continue
                n, avg = stats[doc.tier]
                idf = math.log(1 + (n - df[doc.tier] + 0.5) / (df[doc.tier] + 0.5))
                norm_len = 1 - s.b + s.b * doc.length / avg
                sums[doc_id] += idf * tf * (s.k1 + 1) / (tf + s.k1 * norm_len)
                matched[doc_id] += 1
        return {
            doc_id: total * (matched[doc_id] / len(terms)) ** s.coverage_power
            for doc_id, total in sums.items()
            if total > 0
        }

    def _name_tiers(self, query: str, scores: dict[int, float]) -> dict[int, int]:
        if not self.settings.exact_name_first:
            return {}
        qnames = {norm(query), *(norm(word) for word in query.split())}
        kinds = self.store.exact_names(name for name in qnames if name)
        return {doc: kind for doc, kind in kinds.items() if doc in scores}

    def _ranked(self, doc: DocRow, score: float, name_tier: int) -> Ranked:
        if doc.tier != RECORDS:
            return Ranked(doc, score, False, (), NO_NAME)
        replaced = sorted(self._replacements().get(doc.path, ()))
        superseded = bool(replaced) or doc.status.lower() in self.settings.superseded_status
        if superseded:
            score *= self.settings.superseded_factor
        return Ranked(doc, score, superseded, tuple(replaced), name_tier)

    def _order(self, tier: str, items: list[Ranked]) -> list[Ranked]:
        rank_of = self.settings.rank_of

        def key(item: Ranked) -> tuple:
            path = item.doc.path
            if item.name_tier < NO_NAME:
                return (item.name_tier, item.superseded, rank_of(path), -item.score, path)
            return (NO_NAME, False, 0, -item.score, path)

        if tier != RECORDS:
            return sorted(items, key=lambda i: (-i.score, i.doc.path))
        return sorted(items, key=key)
