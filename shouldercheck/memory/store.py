"""The derived index: a SQLite file outside the record base, or the same schema in memory.

It holds only what can be recomputed from the record base, so it is safe to delete. A change in
the profile, the tokenizer or the schema rebuilds it; otherwise only files whose size or
modification time changed are parsed again.
"""

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from operator import itemgetter
from pathlib import Path

from shouldercheck.memory import defaults
from shouldercheck.memory.docs import Unit, decode, is_generated, record_unit, tier_units
from shouldercheck.memory.settings import RECORDS, FindSettings
from shouldercheck.records.config import Config
from shouldercheck.records.corpus import Corpus
from shouldercheck.records.scan import Scan

BUSY_TIMEOUT = 5.0
TABLES = ("meta", "file", "doc", "post", "docterms", "link", "name", "alias")
SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE file(path TEXT PRIMARY KEY, size INT, mtime_ns INT, tier TEXT);
CREATE TABLE doc(id INTEGER PRIMARY KEY, file TEXT, path TEXT, tier TEXT, len INT, title TEXT,
                 summary TEXT, aliases TEXT, tags TEXT, status TEXT);
CREATE INDEX doc_file ON doc(file);
CREATE TABLE post(term TEXT, doc INT, tf REAL, PRIMARY KEY(term, doc)) WITHOUT ROWID;
CREATE TABLE docterms(doc INTEGER PRIMARY KEY, terms TEXT);
CREATE TABLE link(doc INT, target TEXT, relation TEXT, dst TEXT);
CREATE INDEX link_doc ON link(doc);
CREATE INDEX link_dst ON link(dst);
CREATE TABLE name(norm TEXT, doc INT, kind INT);
CREATE INDEX name_norm ON name(norm);
CREATE TABLE alias(norm TEXT, doc INT);
CREATE INDEX alias_norm ON alias(norm);
"""


@dataclass(frozen=True)
class DocRow:
    id: int
    path: str
    tier: str
    length: int
    title: str
    status: str


@dataclass(frozen=True)
class LinkRow:
    path: str
    target: str
    relation: str
    dst: str | None


class StoreError(Exception):
    """The index cannot be opened or written."""


def root_hash(root: Path) -> str:
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]


def config_hash(cfg: Config) -> str:
    material = {
        "include": cfg.include.patterns,
        "exclude": cfg.exclude.patterns,
        "max_read_chars": cfg.max_read_chars,
        "find": cfg.find,
    }
    blob = json.dumps(material, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def xdg(name: str, fallback: str) -> Path:
    base = os.environ.get(name)
    return Path(base) if base else Path.home() / fallback


def default_cache_dir(root: Path) -> Path:
    return xdg("XDG_CACHE_HOME", ".cache") / "shck" / root_hash(root)


class Store:
    def __init__(self, conn: sqlite3.Connection, in_memory: bool) -> None:
        self.conn = conn
        self.in_memory = in_memory
        self.state = "memory" if in_memory else "warm"
        self._docs: dict[int, DocRow] | None = None

    # -- opening ---------------------------------------------------------------------------

    @classmethod
    def memory(cls) -> "Store":
        conn = sqlite3.connect(":memory:")
        conn.isolation_level = None
        return cls(conn, True)

    @classmethod
    def on_disk(cls, path: Path) -> "Store":
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT)
            conn.isolation_level = None
            conn.execute("PRAGMA journal_mode=WAL")
            path.chmod(0o600)
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-65536")
        except (OSError, sqlite3.Error) as exc:
            raise StoreError(f"cannot open index {path}: {exc}") from exc
        return cls(conn, False)

    def close(self) -> None:
        self.conn.close()

    # -- freshness -------------------------------------------------------------------------

    def refresh(
        self, cfg: Config, settings: FindSettings, scan: Scan, tier_of: Callable[[str], str | None]
    ) -> str:
        """Bring the index up to date with the tree; returns warm, incremental or cold."""
        wanted = _stat_files(cfg, scan, tier_of)
        expect = {
            "schema": str(defaults.SCHEMA_VERSION),
            "tokenizer": str(defaults.TOKENIZER_VERSION),
            "config": config_hash(cfg),
            "tree": _tree_signature(scan),
        }
        if self._plan(wanted, expect) == (False, [], []) and self._tree_is(expect["tree"]):
            return "warm"
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise StoreError(f"index is locked: {exc}") from exc
        try:
            # Another process may have brought the index up to date while we waited.
            rebuild, changed, removed = self._plan(wanted, expect)
            if rebuild:
                self._reset()
            stored = {} if rebuild else self._files()
            relink = not rebuild and not self._tree_is(expect["tree"])
            if rebuild or changed or removed or relink:
                self._apply(cfg, settings, scan, wanted, stored, changed, removed, relink)
            for key, value in expect.items():
                self._set_meta(key, value)
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self._docs = None
        result = "cold" if rebuild else "incremental"
        self.state = "memory" if self.in_memory else result
        return result

    def _plan(
        self, wanted: dict[str, tuple[int, int, str]], expect: dict[str, str]
    ) -> tuple[bool, list[str], list[str]]:
        """(rebuild, files to parse, files to forget) to reach `wanted`."""
        meta = self._meta()
        if any(meta.get(key) != expect[key] for key in ("schema", "tokenizer", "config")):
            return True, list(wanted), []
        stored = self._files()
        changed = [p for p, row in wanted.items() if stored.get(p) != row]
        removed = [p for p in stored if p not in wanted]
        return False, changed, removed

    def _tree_is(self, signature: str) -> bool:
        return self._meta().get("tree") == signature

    def _meta(self) -> dict[str, str]:
        try:
            return dict(self.conn.execute("SELECT key, value FROM meta"))
        except sqlite3.OperationalError:
            return {}

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def _files(self) -> dict[str, tuple[int, int, str]]:
        try:
            rows = self.conn.execute("SELECT path, size, mtime_ns, tier FROM file")
        except sqlite3.OperationalError:
            return {}
        return {path: (size, mtime, tier) for path, size, mtime, tier in rows}

    def _reset(self) -> None:
        for table in TABLES:
            self.conn.execute(f"DROP TABLE IF EXISTS {table}")
        for statement in SCHEMA.split(";"):
            if statement.strip():
                self.conn.execute(statement)

    def _apply(
        self,
        cfg: Config,
        settings: FindSettings,
        scan: Scan,
        wanted: dict[str, tuple[int, int, str]],
        stored: dict[str, tuple[int, int, str]],
        changed: list[str],
        removed: list[str],
        relink: bool,
    ) -> None:
        corpus = Corpus(cfg, scan, {})
        for path in removed:
            self._forget(path)
        postings: list[tuple[str, int, float]] = []
        for path in changed:
            if path in stored:
                self._forget(path)
            size, mtime, tier = wanted[path]
            self.conn.execute("INSERT INTO file VALUES (?, ?, ?, ?)", (path, size, mtime, tier))
            for unit in _read_units(cfg, settings, path, tier):
                postings += self._insert(path, unit, corpus)
        if postings:
            # Documents are inserted in id order, so a stable sort by term keeps (term, doc) sorted.
            postings.sort(key=itemgetter(0))
            self.conn.executemany("INSERT INTO post VALUES (?, ?, ?)", postings)
        if relink:
            self._resolve_links(corpus)

    def _forget(self, path: str) -> None:
        ids = [row[0] for row in self.conn.execute("SELECT id FROM doc WHERE file=?", (path,))]
        for doc in ids:
            row = self.conn.execute("SELECT terms FROM docterms WHERE doc=?", (doc,)).fetchone()
            terms = json.loads(row[0]) if row else []
            self.conn.executemany(
                "DELETE FROM post WHERE term=? AND doc=?", ((t, doc) for t in terms)
            )
            for table, column in (("docterms", "doc"), ("link", "doc"), ("name", "doc")):
                self.conn.execute(f"DELETE FROM {table} WHERE {column}=?", (doc,))
            self.conn.execute("DELETE FROM alias WHERE doc=?", (doc,))
            self.conn.execute("DELETE FROM doc WHERE id=?", (doc,))
        self.conn.execute("DELETE FROM file WHERE path=?", (path,))

    def _insert(self, file: str, unit: Unit, corpus: Corpus) -> list[tuple[str, int, float]]:
        cur = self.conn.execute(
            "INSERT INTO doc(file, path, tier, len, title, summary, aliases, tags, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                file,
                unit.path,
                unit.tier,
                unit.length,
                unit.title,
                unit.summary,
                json.dumps(unit.aliases, ensure_ascii=False),
                json.dumps(unit.tags, ensure_ascii=False),
                unit.status,
            ),
        )
        doc = cur.lastrowid
        assert doc is not None
        self.conn.execute("INSERT INTO docterms VALUES (?, ?)", (doc, json.dumps(list(unit.tf))))
        self.conn.executemany(
            "INSERT INTO name VALUES (?, ?, ?)", ((n, doc, k) for n, k in unit.names)
        )
        self.conn.executemany(
            "INSERT INTO alias VALUES (?, ?)", ((a.lower(), doc) for a in set(unit.aliases))
        )
        self.conn.executemany(
            "INSERT INTO link VALUES (?, ?, ?, ?)",
            (
                (doc, link.target, link.relation, _resolve(corpus, unit.path, link.target))
                for link in unit.links
            ),
        )
        return [(term, doc, weight) for term, weight in unit.tf.items()]

    def _resolve_links(self, corpus: Corpus) -> None:
        rows = self.conn.execute(
            "SELECT link.rowid, doc.path, link.target FROM link JOIN doc ON doc.id = link.doc"
        ).fetchall()
        self.conn.executemany(
            "UPDATE link SET dst=? WHERE rowid=?",
            ((_resolve(corpus, path, target), rowid) for rowid, path, target in rows),
        )

    # -- queries ---------------------------------------------------------------------------

    def docs(self) -> dict[int, DocRow]:
        if self._docs is None:
            rows = self.conn.execute("SELECT id, path, tier, len, title, status FROM doc")
            self._docs = {row[0]: DocRow(*row) for row in rows}
        return self._docs

    def postings(self, term: str) -> list[tuple[int, float]]:
        return self.conn.execute("SELECT doc, tf FROM post WHERE term=?", (term,)).fetchall()

    def exact_names(self, names: Iterable[str]) -> dict[int, int]:
        """Best kind per document for the given normalised names (0 beats 1)."""
        found: dict[int, int] = {}
        for name in set(names):
            for doc, kind in self.conn.execute("SELECT doc, kind FROM name WHERE norm=?", (name,)):
                found[doc] = min(kind, found.get(doc, kind))
        return found

    def link_rows(self, relations: Iterable[str]) -> list[tuple[str, str, str]]:
        """(source path, relation word, destination path) of resolved links with these words."""
        words = list(relations)
        if not words:
            return []
        marks = ",".join("?" * len(words))
        sql = (
            "SELECT doc.path, link.relation, link.dst FROM link JOIN doc ON doc.id = link.doc"
            f" WHERE link.dst IS NOT NULL AND link.relation IN ({marks})"
        )
        return self.conn.execute(sql, words).fetchall()

    def outgoing(self, doc: int) -> list[LinkRow]:
        rows = self.conn.execute(
            "SELECT doc.path, target, relation, dst FROM link JOIN doc ON doc.id = link.doc"
            " WHERE link.doc=? ORDER BY link.rowid",
            (doc,),
        )
        return [LinkRow(*row) for row in rows]

    def incoming(self, path: str) -> list[LinkRow]:
        rows = self.conn.execute(
            "SELECT doc.path, target, relation, dst FROM link JOIN doc ON doc.id = link.doc"
            " WHERE link.dst=? AND doc.path != ? AND doc.tier = ? ORDER BY doc.path, link.rowid",
            (path, path, RECORDS),
        )
        return [LinkRow(*row) for row in rows]

    def alias_owners(self, doc: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT other.path FROM alias mine"
            " JOIN alias theirs ON theirs.norm = mine.norm"
            " JOIN doc other ON other.id = theirs.doc WHERE mine.doc=? AND theirs.doc != ?"
            " ORDER BY other.path",
            (doc, doc),
        )
        return [row[0] for row in rows]

    def aliases_of(self, doc: int) -> list[str]:
        row = self.conn.execute("SELECT aliases FROM doc WHERE id=?", (doc,)).fetchone()
        return json.loads(row[0]) if row else []


def _resolve(corpus: Corpus, doc_path: str, target: str) -> str | None:
    base = doc_path.split("#", 1)[0]
    resolution = corpus.resolve(base, target)
    return resolution.path if resolution.kind == "file" else None


def _tree_signature(scan: Scan) -> str:
    return hashlib.sha1("\n".join(sorted(scan.all_files)).encode("utf-8")).hexdigest()


def _stat_files(
    cfg: Config, scan: Scan, tier_of: Callable[[str], str | None]
) -> dict[str, tuple[int, int, str]]:
    found: dict[str, tuple[int, int, str]] = {}
    for rel in sorted(scan.all_files):
        tier = tier_of(rel)
        if tier is None:
            continue
        try:
            st = os.stat(cfg.root / rel)
        except OSError:
            continue
        if st.st_size > cfg.max_read_chars:
            continue
        found[rel] = (st.st_size, st.st_mtime_ns, tier)
    return found


def _read_units(cfg: Config, settings: FindSettings, rel: str, tier: str) -> list[Unit]:
    try:
        text = decode((cfg.root / rel).read_bytes())
    except OSError:
        return []
    if is_generated(text):
        return []
    if tier == RECORDS:
        return [record_unit(rel, text, settings)]
    spec = settings.tier(tier)
    return tier_units(rel, text, spec, settings) if spec else []


def tier_selector(cfg: Config, settings: FindSettings, scan: Scan) -> Callable[[str], str | None]:
    """Which tier a file belongs to; the top-level scope wins over a tier's globs.

    The scan already decided the records, so only the other files are matched against tiers.
    """
    records = set(scan.paths)

    def select(rel: str) -> str | None:
        if rel in records:
            return RECORDS
        for tier in settings.tiers:
            if tier.include(rel) and not tier.exclude(rel):
                # Records and excluded files never reach a tier.
                return None if cfg.exclude(rel) or cfg.include(rel) else tier.name
        return None

    return select
