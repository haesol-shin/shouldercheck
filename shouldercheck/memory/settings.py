"""Typed, validated view of the `[find]` profile table."""

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from shouldercheck.memory import defaults
from shouldercheck.memory.tokens import Masker
from shouldercheck.records.config import Config, ConfigError
from shouldercheck.records.globs import Globs

FIND_KEYS = {
    "weights",
    "k1",
    "b",
    "coverage_power",
    "superseded_factor",
    "superseded_status",
    "relations",
    "priority",
    "exact_name_first",
    "mask",
    "tiers",
    "cache_dir",
    "log",
    "neighbors",
}
LOG_KEYS = {"dir", "keep_days", "max_bytes_per_day", "log_top", "max_line_bytes"}
TIER_KEYS = {"name", "include", "exclude", "unit", "entry_pattern", "anchor_prefix", "max_hits"}
TIER_UNITS = ("file", "entry")
RECORDS = "records"


@dataclass(frozen=True)
class Tier:
    name: str
    include: Globs
    exclude: Globs
    unit: str
    entry_pattern: re.Pattern[str] | None
    anchor_prefix: str
    max_hits: int


@dataclass(frozen=True)
class LogSettings:
    dir: str | None
    keep_days: int
    max_bytes_per_day: int
    log_top: int
    max_line_bytes: int


@dataclass(frozen=True)
class Relations:
    """Relation words by name; the regex finds one in the text before a link."""

    words: dict[str, tuple[str, ...]]
    regex: re.Pattern[str] | None
    names: dict[str, str]

    def name_of(self, word: str) -> str | None:
        return self.names.get(word)

    def words_of(self, name: str) -> tuple[str, ...]:
        return self.words.get(name, ())


@dataclass(frozen=True)
class FindSettings:
    weights: dict[str, float]
    k1: float
    b: float
    coverage_power: float
    superseded_factor: float
    superseded_status: tuple[str, ...]
    relations: Relations
    priority: tuple[tuple[Globs, int], ...]
    exact_name_first: bool
    masker: Masker
    tiers: tuple[Tier, ...]
    cache_dir: str | None
    log: LogSettings
    neighbors: int

    def rank_of(self, rel: str) -> int:
        for glob, rank in self.priority:
            if glob(rel):
                return rank
        return defaults.DEFAULT_RANK

    def tier(self, name: str) -> Tier | None:
        return next((tier for tier in self.tiers if tier.name == name), None)


def _where(cfg: Config) -> str:
    return cfg.display_path or "built-in profile"


def _table(value: object, key: str, allowed: set[str], where: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: [{key}] must be a table")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigError(f"{where}: [{key}] unknown key(s): {', '.join(unknown)}")
    return value


def _strings(value: object, key: str, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{where}: {key} must be a list of strings")
    return tuple(value)


def _number(table: dict, key: str, default: float, minimum: float, where: str) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value < minimum:
        raise ConfigError(f"{where}: {key} must be a number of at least {minimum}")
    return value


def _integer(table: dict, key: str, default: int, minimum: int, where: str) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{where}: {key} must be an integer of at least {minimum}")
    return value


def _patterns(items: tuple[str, ...], where: str) -> tuple[re.Pattern[str], ...]:
    compiled = []
    for item in items:
        try:
            compiled.append(re.compile(item))
        except re.error as exc:
            raise ConfigError(f"{where}: bad regex {item!r}: {exc}") from exc
    return tuple(compiled)


def _globs(items: tuple[str, ...], where: str) -> Globs:
    try:
        return Globs(items)
    except ValueError as exc:
        raise ConfigError(f"{where}: {exc}") from exc


def _weights(table: dict, where: str) -> dict[str, float]:
    given = _table(table.get("weights", {}), "find.weights", set(defaults.WEIGHTS), where)
    weights = dict(defaults.WEIGHTS)
    for key in given:
        weights[key] = _number(given, key, 0, 0, f"{where}: [find.weights]")
    return weights


def _relations(table: dict, where: str) -> Relations:
    given = _table(table.get("relations", {}), "find.relations", set(defaults.RELATIONS), where)
    words = dict(defaults.RELATIONS)
    for name, value in given.items():
        words[name] = _strings(value, f"[find.relations] {name}", where)
    names = {word: name for name, items in words.items() for word in items if word}
    # Longest word first, so "superseded_by" is not read as a shorter word that is a prefix of it.
    ordered = sorted(names, key=len, reverse=True)
    regex = re.compile("(" + "|".join(map(re.escape, ordered)) + r")\**\s*:") if ordered else None
    return Relations(words, regex, names)


def _priority(table: dict, where: str) -> tuple[tuple[Globs, int], ...]:
    entries = table.get("priority", [])
    if not isinstance(entries, list):
        raise ConfigError(f"{where}: [[find.priority]] must be an array of tables")
    result = []
    for entry in entries:
        entry = _table(entry, "find.priority", {"glob", "rank"}, where)
        glob = entry.get("glob")
        if not isinstance(glob, str):
            raise ConfigError(f"{where}: [[find.priority]] needs a glob")
        rank = _integer(entry, "rank", defaults.DEFAULT_RANK, 0, where)
        result.append((_globs((glob,), where), rank))
    return tuple(result)


def _tier(entry: object, where: str) -> Tier:
    entry = _table(entry, "find.tiers", TIER_KEYS, where)
    name = entry.get("name")
    if not isinstance(name, str) or not name or name == RECORDS:
        raise ConfigError(f"{where}: [[find.tiers]] needs a name other than {RECORDS!r}")
    unit = entry.get("unit", "file")
    if unit not in TIER_UNITS:
        raise ConfigError(f"{where}: tier {name} unit must be one of {', '.join(TIER_UNITS)}")
    pattern = None
    if unit == "entry":
        raw = entry.get("entry_pattern")
        if not isinstance(raw, str):
            raise ConfigError(f"{where}: tier {name} needs an entry_pattern")
        pattern = _patterns((raw,), where)[0]
        if pattern.groups < 1:
            raise ConfigError(f"{where}: tier {name} entry_pattern needs a capture group")
    prefix = entry.get("anchor_prefix", "")
    if not isinstance(prefix, str):
        raise ConfigError(f"{where}: tier {name} anchor_prefix must be a string")
    include = _strings(entry.get("include", []), "include", where)
    if not include:
        raise ConfigError(f"{where}: tier {name} needs include globs")
    return Tier(
        name=name,
        include=_globs(include, where),
        exclude=_globs(_strings(entry.get("exclude", []), "exclude", where), where),
        unit=unit,
        entry_pattern=pattern,
        anchor_prefix=prefix,
        max_hits=_integer(entry, "max_hits", defaults.TIER_MAX_HITS, 1, where),
    )


def _tiers(table: dict, where: str) -> tuple[Tier, ...]:
    entries = table.get("tiers", [])
    if not isinstance(entries, list):
        raise ConfigError(f"{where}: [[find.tiers]] must be an array of tables")
    tiers = tuple(_tier(entry, where) for entry in entries)
    names = [tier.name for tier in tiers]
    if len(set(names)) != len(names):
        raise ConfigError(f"{where}: [[find.tiers]] names must be unique")
    return tiers


def _optional_path(table: dict, key: str, where: str) -> str | None:
    value = table.get(key)
    if value is not None and not isinstance(value, str):
        raise ConfigError(f"{where}: {key} must be a string")
    return value


def _log(table: dict, where: str) -> LogSettings:
    log = _table(table.get("log", {}), "find.log", LOG_KEYS, where)
    return LogSettings(
        dir=_optional_path(log, "dir", where),
        keep_days=_integer(log, "keep_days", defaults.LOG_KEEP_DAYS, 1, where),
        max_bytes_per_day=_integer(
            log, "max_bytes_per_day", defaults.LOG_MAX_BYTES_PER_DAY, 1, where
        ),
        log_top=_integer(log, "log_top", defaults.LOG_TOP, 0, where),
        max_line_bytes=_integer(log, "max_line_bytes", defaults.LOG_MAX_LINE_BYTES, 256, where),
    )


def find_settings(cfg: Config) -> FindSettings:
    where = _where(cfg)
    table = _table(cfg.find, "find", FIND_KEYS, where)
    exact = table.get("exact_name_first", True)
    if not isinstance(exact, bool):
        raise ConfigError(f"{where}: exact_name_first must be true or false")
    status = table.get("superseded_status", list(defaults.SUPERSEDED_STATUS))
    return FindSettings(
        weights=_weights(table, where),
        k1=_number(table, "k1", defaults.K1, 0, where),
        b=_number(table, "b", defaults.B, 0, where),
        coverage_power=_number(table, "coverage_power", defaults.COVERAGE_POWER, 0, where),
        superseded_factor=_number(table, "superseded_factor", defaults.SUPERSEDED_FACTOR, 0, where),
        superseded_status=tuple(s.lower() for s in _strings(status, "superseded_status", where)),
        relations=_relations(table, where),
        priority=_priority(table, where),
        exact_name_first=exact,
        masker=Masker(_patterns(_strings(table.get("mask", []), "mask", where), where)),
        tiers=_tiers(table, where),
        cache_dir=_optional_path(table, "cache_dir", where),
        log=_log(table, where),
        neighbors=_integer(table, "neighbors", defaults.NEIGHBORS, 0, where),
    )


def resolve_dir(configured: str | None, cfg: Config, default: Path) -> Path:
    """A profile folder is relative to the profile file; the default has no profile to follow."""
    if configured is None:
        return default
    base = cfg.path.parent if cfg.path else cfg.root
    return (base / Path(configured).expanduser()).resolve()


INDEX_KEYS = {"map", "title", "header", "top_title", "top_files", "exclude", "sections"}
SECTION_KEYS = {"id", "title", "root", "mode", "cap", "order", "index", "note"}
MODES = ("tree", "recent", "count")
ORDERS = ("path", "name-desc", "mtime-desc")
SECTION_INDEX = ("folder", "none")
DEFAULT_CAP = {"tree": 200, "recent": 20, "count": 200}


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    root: str
    mode: str
    cap: int
    order: str
    index: str
    note: str


@dataclass(frozen=True)
class IndexSettings:
    map: str
    title: str
    header: tuple[str, ...]
    top_title: str
    top_files: tuple[str, ...]
    exclude: Globs
    sections: tuple[Section, ...]


def _relative_folder(value: object, key: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip("/"):
        raise ConfigError(f"{where}: {key} must be a folder relative to the root")
    folder = posixpath.normpath(value.strip("/"))
    if folder == ".." or folder.startswith("../") or folder == ".":
        raise ConfigError(f"{where}: {key} {value!r} leaves the record base")
    return folder


def _text(table: dict, key: str, default: str, where: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{where}: {key} must be a string")
    return value


def _section(entry: object, where: str) -> Section:
    entry = _table(entry, "index.sections", SECTION_KEYS, where)
    ident = entry.get("id")
    if not isinstance(ident, str) or not ident:
        raise ConfigError(f"{where}: [[index.sections]] needs an id")
    here = f"{where}: section {ident}"
    mode = entry.get("mode", "tree")
    if mode not in MODES:
        raise ConfigError(f"{here}: mode must be one of {', '.join(MODES)}")
    order = entry.get("order", "mtime-desc" if mode == "recent" else "path")
    if order not in ORDERS or (order == "mtime-desc" and mode != "recent"):
        raise ConfigError(f"{here}: order {order!r} is not allowed for mode {mode}")
    index = entry.get("index", "folder" if mode == "tree" else "none")
    if index not in SECTION_INDEX:
        raise ConfigError(f"{here}: index must be one of {', '.join(SECTION_INDEX)}")
    root = _relative_folder(entry.get("root"), "root", here)
    return Section(
        id=ident,
        title=_text(entry, "title", ident, here),
        root=root,
        mode=mode,
        cap=_integer(entry, "cap", DEFAULT_CAP[mode], 1, here),
        order=order,
        index=index,
        note=_text(entry, "note", "", here),
    )


def _sections(table: dict, where: str) -> tuple[Section, ...]:
    entries = table.get("sections", [])
    if not isinstance(entries, list):
        raise ConfigError(f"{where}: [[index.sections]] must be an array of tables")
    sections = tuple(_section(entry, where) for entry in entries)
    for name, values in (("id", [s.id for s in sections]), ("root", [s.root for s in sections])):
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            raise ConfigError(f"{where}: [[index.sections]] repeats {name} {', '.join(repeated)}")
    return sections


def index_settings(cfg: Config) -> IndexSettings:
    where = _where(cfg)
    table = _table(cfg.index, "index", INDEX_KEYS, where)
    header = _strings(table.get("header", []), "header", where)
    top = _strings(table.get("top_files", []), "top_files", where)
    sections = _sections(table, where)
    if not sections:
        raise ConfigError(
            f"{where}: no [[index.sections]]; add one, for example "
            'id = "notes", root = "notes", mode = "tree"'
        )
    return IndexSettings(
        map=_relative_folder(table.get("map", "index.md"), "map", where),
        title=_text(table, "title", "Index", where),
        header=header,
        top_title=_text(table, "top_title", "Top", where),
        top_files=top,
        exclude=_globs(_strings(table.get("exclude", []), "exclude", where), where),
        sections=sections,
    )


EVAL_KEYS = {"dir", "git_dir", "k", "rank_cap", "abstain_below"}
DEFAULT_K = (1, 3, 10)
RANK_CAP = 50


@dataclass(frozen=True)
class EvalSettings:
    dir: str | None
    git_dir: str | None
    k: tuple[int, ...]
    rank_cap: int
    abstain_below: float | None


def eval_settings(cfg: Config) -> EvalSettings:
    where = _where(cfg)
    table = _table(cfg.eval, "eval", EVAL_KEYS, where)
    ks = table.get("k", list(DEFAULT_K))
    if (
        not isinstance(ks, list)
        or not ks
        or not all(isinstance(k, int) and not isinstance(k, bool) and k >= 1 for k in ks)
    ):
        raise ConfigError(f"{where}: [eval] k must be a list of positive integers")
    below = table.get("abstain_below")
    if below is not None and (isinstance(below, bool) or not isinstance(below, int | float)):
        raise ConfigError(f"{where}: [eval] abstain_below must be a number")
    return EvalSettings(
        dir=_optional_path(table, "dir", where),
        git_dir=_optional_path(table, "git_dir", where),
        k=tuple(sorted(set(ks))),
        rank_cap=_integer(table, "rank_cap", RANK_CAP, 1, where),
        abstain_below=below,
    )
