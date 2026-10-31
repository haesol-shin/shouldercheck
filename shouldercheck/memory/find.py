"""`shck find`: open the index, rank, and describe the hits."""

import sqlite3
import sys
import time
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from shouldercheck.memory import defaults
from shouldercheck.memory.docs import (
    FIELD_LABELS,
    Fields,
    decode,
    read_fields,
    split_entries,
)
from shouldercheck.memory.rank import Ranked, Ranker
from shouldercheck.memory.settings import RECORDS, FindSettings, find_settings, resolve_dir
from shouldercheck.memory.store import (
    LinkRow,
    Store,
    StoreError,
    default_cache_dir,
    tier_selector,
)
from shouldercheck.memory.tokens import Masker, tokenize
from shouldercheck.records.config import Config
from shouldercheck.records.scan import scan_tree

SCOPES = ("records", "transcript", "all")
CACHE_FILE = "find.sqlite"
WINDOW_LEAD = 40


class InputError(Exception):
    """The record base cannot be read (exit 3)."""


@dataclass
class Index:
    """An open, fresh index and the settings that built it."""

    cfg: Config
    settings: FindSettings
    store: Store
    ranker: Ranker
    state: str
    build_ms: int
    docs: int = 0

    def close(self) -> None:
        self.store.close()


@dataclass
class Result:
    query: str
    index: Index
    hits: list[dict] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    ranked: list[tuple[str, float, str]] = field(default_factory=list)
    total_hits: int = 0
    ms: int = 0

    def to_json(self) -> dict:
        return {
            "schema_version": 1,
            "query": self.query,
            "index": {
                "state": self.index.state,
                "docs": self.index.docs,
                "ms": self.index.build_ms,
            },
            "hits": self.hits,
            "transcript": self.transcript,
        }


def open_index(
    cfg: Config,
    settings: FindSettings,
    *,
    use_cache: bool = True,
    cache_file: Path | None = None,
) -> Index:
    """Open the cache (or build in memory) and bring it up to date with the tree."""
    start = time.perf_counter()
    if not cfg.root.is_dir():
        raise InputError(f"record base not found: {cfg.root}")
    tier_of = tier_selector(cfg, settings)
    store = _open_store(cfg, settings, use_cache, cache_file)
    scan = scan_tree(cfg)
    try:
        store.refresh(cfg, settings, scan, tier_of)
    except (StoreError, OSError, sqlite3.Error) as exc:
        if store.in_memory:
            raise
        print(f"shck: {exc}; building in memory instead", file=sys.stderr)
        store.close()
        store = Store.memory()
        store.refresh(cfg, settings, scan, tier_of)
    ms = int((time.perf_counter() - start) * 1000)
    ranker = Ranker(store, settings)
    return Index(cfg, settings, store, ranker, store.state, ms, ranker.count(RECORDS))


def _open_store(
    cfg: Config, settings: FindSettings, use_cache: bool, cache_file: Path | None
) -> Store:
    if not use_cache:
        return Store.memory()
    folder = resolve_dir(settings.cache_dir, cfg, default_cache_dir(cfg.root))
    try:
        return Store.on_disk(cache_file or folder / CACHE_FILE)
    except StoreError as exc:
        print(f"shck: {exc}; building in memory instead", file=sys.stderr)
        return Store.memory()


def run_find(
    cfg: Config,
    query: str,
    *,
    limit: int = 10,
    scope: str = "all",
    neighbors: int | None = None,
    use_cache: bool = True,
    skip_files: Collection[str] = (),
    index: Index | None = None,
) -> Result:
    started = time.perf_counter()
    settings = find_settings(cfg)
    opened = index or open_index(cfg, settings, use_cache=use_cache)
    try:
        return _search(cfg, settings, opened, query, limit, scope, neighbors, skip_files, started)
    finally:
        if index is None:
            opened.close()


def _search(
    cfg: Config,
    settings: FindSettings,
    index: Index,
    query: str,
    limit: int,
    scope: str,
    neighbors: int | None,
    skip_files: Collection[str],
    started: float,
) -> Result:
    shown = settings.neighbors if neighbors is None else neighbors
    tiers = _scope_tiers(scope, index)
    ranked = index.ranker.rank(query, tiers)
    result = Result(query, index)
    records = [r for r in ranked.get(RECORDS, []) if r.doc.path not in skip_files]
    result.total_hits = len(records)
    describer = _Describer(index, query, shown)
    for rank, item in enumerate(records[:limit], 1):
        result.hits.append(describer.record(rank, item))
    rank = len(result.hits)
    for tier in settings.tiers:
        found = [r for r in ranked.get(tier.name, []) if r.doc.path.split("#")[0] not in skip_files]
        for item in found[: tier.max_hits]:
            rank += 1
            result.transcript.append(describer.entry(rank, item))
    result.ranked = _flat(ranked, settings, skip_files)
    result.ms = int((time.perf_counter() - started) * 1000)
    return result


def _flat(
    ranked: dict[str, list[Ranked]], settings: FindSettings, skip: Collection[str]
) -> list[tuple[str, float, str]]:
    order = [RECORDS, *(tier.name for tier in settings.tiers)]
    return [
        (item.doc.path, item.score, tier)
        for tier in order
        for item in ranked.get(tier, [])
        if item.doc.path.split("#")[0] not in skip
    ]


def _scope_tiers(scope: str, index: Index) -> list[str]:
    extra = [tier.name for tier in index.settings.tiers]
    if scope == "records":
        return [RECORDS]
    if scope == "transcript":
        return extra
    return [RECORDS, *extra]


def rank_records(index: Index, query: str) -> list[Ranked]:
    """The records tier only, best first (used by eval and gaps)."""
    return index.ranker.rank(query, [RECORDS]).get(RECORDS, [])


class _Describer:
    """Fills in what the index does not hold (matched fields, snippet) by re-reading a file."""

    def __init__(self, index: Index, query: str, neighbors: int) -> None:
        self.index = index
        self.masker: Masker = index.settings.masker
        self.terms = set(tokenize(query))
        self.neighbors = neighbors
        self.titles = {d.path: d.title for d in index.store.docs().values() if d.tier == RECORDS}

    def _read(self, rel: str) -> str | None:
        try:
            return decode((self.index.cfg.root / rel).read_bytes())
        except OSError:
            return None

    def record(self, rank: int, item: Ranked) -> dict:
        doc = item.doc
        text = self._read(doc.path)
        fields = read_fields(doc.path, text) if text is not None else None
        matched = self._matched(fields)
        mask = self.masker.clip
        aliases = self.index.store.aliases_of(doc.id)
        outgoing = self.index.store.outgoing(doc.id)
        incoming = self.index.store.incoming(doc.path)
        return {
            "rank": rank,
            "tier": RECORDS,
            "path": mask(doc.path, keep_space=True),
            "score": round(item.score, 3),
            "matched": matched,
            "title": mask(doc.title),
            "summary": mask(fields.summary) if fields else "",
            "snippet": self._snippet(fields),
            "status": mask(doc.status) or None,
            "superseded": item.superseded,
            "replaced_by": [mask(p, keep_space=True) for p in item.replaced_by],
            "same_alias_as": [
                mask(p, keep_space=True) for p in self.index.store.alias_owners(doc.id)
            ],
            "aliases": [mask(a) for a in aliases],
            "outgoing": self._outgoing(outgoing),
            "incoming": self._incoming(incoming),
            "outgoing_total": len(outgoing),
            "incoming_total": len(incoming),
        }

    def entry(self, rank: int, item: Ranked) -> dict:
        doc = item.doc
        rel, _, fragment = doc.path.partition("#")
        text = self._read(rel)
        body = ""
        spec = self.index.settings.tier(doc.tier)
        if text is not None and spec is not None:
            if spec.unit == "entry":
                found = [e for e in split_entries(text, spec) if e[0] == fragment]
                body = found[0][2] if found else ""
            else:
                body = text
        return {
            "rank": rank,
            "tier": doc.tier,
            "path": self.masker.clip(doc.path, keep_space=True),
            "score": round(item.score, 3),
            "title": self.masker.clip(doc.title),
            "snippet": self._window(body.split("\n")) if body else "",
        }

    def _matched(self, fields: Fields | None) -> list[str]:
        if fields is None:
            return []
        return [
            FIELD_LABELS[name]
            for name, value in fields.values.items()
            if self.terms & set(tokenize(value))
        ]

    def _snippet(self, fields: Fields | None) -> str:
        if fields is None:
            return ""
        return self._window(fields.lines[fields.start :]) or self.masker.clip(fields.summary)

    def _window(self, lines: list[str]) -> str:
        """The best-matching line, masked first and then cut around the first matching word."""
        best, best_count = "", 0
        for line in lines:
            count = len(self.terms & set(tokenize(line)))
            if count > best_count:
                best, best_count = line, count
        if not best_count:
            return ""
        line = " ".join(self.masker.mask(best).split())
        if len(line) > defaults.SNIPPET_CHARS:
            offset = 0
            for word in line.split(" "):
                if self.terms & set(tokenize(word)):
                    break
                offset += len(word) + 1
            line = line[max(0, offset - WINDOW_LEAD) :]
        return self.masker.clip(line)

    def _title(self, path: str | None) -> str:
        return self.masker.clip(self.titles.get(path or "", ""))

    def _outgoing(self, rows: list[LinkRow]) -> list[dict]:
        mask = self.masker.clip
        return [
            {
                "relation": row.relation or "link",
                "path": mask(row.dst, keep_space=True) if row.dst else None,
                "target": mask(row.target, keep_space=True),
                "title": self._title(row.dst),
                "broken": row.dst is None,
            }
            for row in rows[: self.neighbors]
        ]

    def _incoming(self, rows: list[LinkRow]) -> list[dict]:
        return [
            {
                "relation": row.relation or "link",
                "path": self.masker.clip(row.path, keep_space=True),
                "title": self._title(row.path),
            }
            for row in rows[: self.neighbors]
        ]


def render_text(result: Result) -> str:
    if not result.hits and not result.transcript:
        return "no results\n"
    lines: list[str] = []
    for hit in result.hits:
        lines += _block(hit)
    if result.transcript:
        lines.append("transcript (low rank, not records)")
        for hit in result.transcript:
            lines += _block(hit)
    return "\n".join(lines) + "\n"


def _block(hit: dict) -> list[str]:
    tag = " [superseded]" if hit.get("superseded") else ""
    lines = [
        f"{hit['rank']}. {hit['path']}{tag}  (score {hit['score']})",
        f"   title: {hit['title']}",
    ]
    if hit.get("matched"):
        lines.append("   matched: " + ", ".join(hit["matched"]))
    if hit.get("summary"):
        lines.append(f"   summary: {hit['summary']}")
    if hit.get("snippet"):
        lines.append(f"   snippet: {hit['snippet']}")
    if hit.get("status"):
        lines.append(f"   status: {hit['status']}")
    lines += [f"   replaced by: {path}" for path in hit.get("replaced_by", [])]
    if hit.get("same_alias_as"):
        lines.append("   same alias: " + ", ".join(hit["same_alias_as"]))
    for item in hit.get("outgoing", []):
        where = item["path"] or f"{item['target']} (broken)"
        title = f" - {item['title']}" if item["title"] else ""
        lines.append(f"   -> {item['relation']}: {where}{title}")
    more = hit.get("outgoing_total", 0) - len(hit.get("outgoing", []))
    if more > 0:
        lines.append(f"   -> ... {more} more outgoing")
    for item in hit.get("incoming", []):
        title = f" - {item['title']}" if item["title"] else ""
        lines.append(f"   <- {item['relation']}: {item['path']}{title}")
    more = hit.get("incoming_total", 0) - len(hit.get("incoming", []))
    if more > 0:
        lines.append(f"   <- ... {more} more incoming")
    return lines
