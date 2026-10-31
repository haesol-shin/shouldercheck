"""Load and validate the TOML profile of one record base."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from shouldercheck.records.findings import SEVERITIES
from shouldercheck.records.globs import Globs

CONFIG_NAMES = ("shck.toml", ".shck.toml")
CHECK_NAMES = (
    "dead-link",
    "dead-anchor",
    "orphan",
    "missing-field",
    "alias-dup",
    "size",
    "dup-content",
    "stale",
    "ignore-without-reason",
)
# On without input: dead-link, dead-anchor, alias-dup. Orphan and missing-field need a scope or
# rules to find anything. Size, dup-content and stale are opt-in through [checks].
DEFAULT_CHECKS = {
    "dead-link": "error",
    "dead-anchor": "error",
    "orphan": "warn",
    "missing-field": "warn",
    "alias-dup": "error",
    "ignore-without-reason": "warn",
}
FIELD_RULE_KEYS = {"match", "folder_any", "require", "values", "body_lines", "body_lines_max"}
SIZE_KEYS = {"warn_chars", "high_chars", "max_line_chars", "map_budget_chars", "maps", "exclude"}
ORPHAN_KEYS = {"scope", "catalog", "exempt", "exempt_names", "unit", "folder_depth", "grace_days"}
LINK_STYLES = ("markdown", "wiki", "backtick")
DEFAULT_LINKS = ("markdown", "wiki")
WIKI_RESOLVE = ("stem", "title", "path")
SLUGS = ("github", "mkdocs", "obsidian")
LINK_OPT_KEYS = {"wiki_resolve", "slug", "heading_ids", "html_ids", "backtick_dead", "link_dirs"}
DEFAULT_INCLUDE = ("**/*.md",)
DEFAULT_EXCLUDE = (".*/**", "node_modules/**", "**/*sfconflict*")
FAIL_ON = (*SEVERITIES, "never")
FORMATS = ("text", "json")


class ConfigError(Exception):
    """The profile or the command line is invalid (exit code 2)."""


@dataclass(frozen=True)
class PathIgnore:
    glob: str
    checks: tuple[str, ...]
    reason: str | None
    matcher: Globs = field(compare=False)


@dataclass(frozen=True)
class LinkOpts:
    wiki_resolve: str = "stem"
    slug: str = "github"
    heading_ids: bool = False
    html_ids: bool = False
    backtick_dead: bool = False
    link_dirs: bool = False


@dataclass(frozen=True)
class FieldRule:
    """`match` rules check every matching file; `folder_in` rules need one file per folder."""

    require: tuple[str, ...]
    match: Globs
    folder_in: Globs | None
    when_present: Globs
    values: dict[str, tuple[str, ...]] = field(compare=False)
    body_lines: bool = False
    body_lines_max: int = 12


@dataclass(frozen=True)
class OrphanOpts:
    scope: Globs
    catalog: Globs
    exempt: Globs
    exempt_names: Globs
    unit: str = "file"
    folder_depth: int = 3
    grace_days: int = 0


@dataclass(frozen=True)
class SizeOpts:
    warn_chars: int
    high_chars: int
    max_line_chars: int
    map_budget_chars: int
    maps: Globs
    exclude: Globs


@dataclass(frozen=True)
class StaleOpts:
    match: Globs
    days: int = 14
    field: str = "updated"


@dataclass(frozen=True)
class Config:
    root: Path
    path: Path | None
    include: Globs
    exclude: Globs
    frozen: Globs
    max_read_chars: int
    links: tuple[str, ...]
    opts: LinkOpts
    checks: dict[str, str]
    ignores: tuple[PathIgnore, ...]
    fail_on: str
    format: str
    frozen_manifests: Globs
    orphans: OrphanOpts
    field_rules: tuple[FieldRule, ...]
    size: SizeOpts
    stale: StaleOpts
    find: dict = field(default_factory=dict)
    index: dict = field(default_factory=dict)
    eval: dict = field(default_factory=dict)

    @property
    def display_path(self) -> str | None:
        if self.path is None:
            return None
        try:
            return self.path.relative_to(self.root).as_posix()
        except ValueError:
            return self.path.name

    def severity(self, check: str) -> str | None:
        """Severity of a check's primary findings; None when the check is off."""
        level = self.checks.get(check, "off")
        return None if level == "off" else level


def _table(data: dict, key: str, allowed: set[str], where: str) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: [{key}] must be a table")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) in [{key}]: {', '.join(unknown)}")
    return value


def _strings(table: dict, key: str, default: tuple[str, ...], where: str) -> tuple[str, ...]:
    value = table.get(key, list(default))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{where}: {key} must be a list of strings")
    return tuple(value)


def _globs(table: dict, key: str, default: tuple[str, ...], where: str) -> Globs:
    try:
        return Globs(_strings(table, key, default, where))
    except ValueError as exc:
        raise ConfigError(f"{where}: {exc}") from exc


def _choice(value: object, allowed: tuple[str, ...], what: str, where: str) -> str:
    if value not in allowed:
        raise ConfigError(f"{where}: {what} must be one of {', '.join(allowed)}")
    return str(value)


def _checks(data: dict, where: str) -> dict[str, str]:
    table = _table(data, "checks", set(CHECK_NAMES), where)
    levels = dict(DEFAULT_CHECKS)
    for name, level in table.items():
        levels[name] = _choice(level, (*SEVERITIES, "off"), f"[checks] {name}", where)
    return levels


def _link_styles(data: dict, where: str) -> tuple[str, ...]:
    styles = _strings(data, "links", DEFAULT_LINKS, where)
    for style in styles:
        _choice(style, LINK_STYLES, "links entry", where)
    return styles


def _flag(table: dict, key: str, where: str) -> bool:
    value = table.get(key, False)
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: {key} must be true or false")
    return value


def _link_opts(data: dict, where: str) -> LinkOpts:
    table = _table(data, "links_opts", LINK_OPT_KEYS, where)
    return LinkOpts(
        wiki_resolve=_choice(
            table.get("wiki_resolve", "stem"), WIKI_RESOLVE, "wiki_resolve", where
        ),
        slug=_choice(table.get("slug", "github"), SLUGS, "slug", where),
        heading_ids=_flag(table, "heading_ids", where),
        html_ids=_flag(table, "html_ids", where),
        backtick_dead=_flag(table, "backtick_dead", where),
        link_dirs=_flag(table, "link_dirs", where),
    )


def _ignores(data: dict, where: str) -> tuple[PathIgnore, ...]:
    entries = data.get("per-path-ignores", [])
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ConfigError(f"{where}: per-path-ignores must be an array of tables")
    result = []
    for entry in entries:
        unknown = sorted(set(entry) - {"glob", "checks", "reason"})
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) in per-path-ignores: {', '.join(unknown)}")
        glob = entry.get("glob")
        names = entry.get("checks")
        if not isinstance(glob, str) or not isinstance(names, list):
            raise ConfigError(f"{where}: per-path-ignores needs glob (string) and checks (list)")
        for name in names:
            if name not in CHECK_NAMES:
                raise ConfigError(f"{where}: per-path-ignores: unknown check {name!r}")
        reason = entry.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ConfigError(f"{where}: per-path-ignores reason must be a string")
        try:
            matcher = Globs([glob])
        except ValueError as exc:
            raise ConfigError(f"{where}: {exc}") from exc
        result.append(PathIgnore(glob, tuple(names), (reason or "").strip() or None, matcher))
    return tuple(result)


def discover(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        for name in CONFIG_NAMES:
            if (folder / name).is_file():
                return folder / name
    return None


def _integer(table: dict, key: str, default: int, minimum: int, section: str, where: str) -> int:
    value = table.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ConfigError(f"{where}: [{section}] {key} must be an integer >= {minimum}")
    return value


def _rule_values(rule: dict, where: str) -> dict[str, tuple[str, ...]]:
    table = rule.get("values", {})
    ok = isinstance(table, dict) and all(
        isinstance(v, list) and all(isinstance(i, str) for i in v) for v in table.values()
    )
    if not ok:
        raise ConfigError(f"{where}: [[fields.rules]] values must map keys to lists of strings")
    return {key: tuple(items) for key, items in table.items()}


def _field_rule(rule: dict, where: str) -> FieldRule:
    unknown = sorted(set(rule) - FIELD_RULE_KEYS)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) in [[fields.rules]]: {', '.join(unknown)}")
    if ("match" in rule) == ("folder_any" in rule):
        raise ConfigError(f"{where}: [[fields.rules]] needs exactly one of match, folder_any")
    require = _strings(rule, "require", (), where)
    if not require:
        raise ConfigError(f"{where}: [[fields.rules]] require must list at least one key")
    folder = (
        _table(rule, "folder_any", {"in", "when_present"}, where) if "folder_any" in rule else {}
    )
    return FieldRule(
        require=require,
        match=_globs(rule, "match", (), where),
        folder_in=_globs(folder, "in", (), where) if "folder_any" in rule else None,
        when_present=_globs(folder, "when_present", (), where),
        values=_rule_values(rule, where),
        body_lines=_flag(rule, "body_lines", where),
        body_lines_max=_integer(rule, "body_lines_max", 12, 1, "fields.rules", where),
    )


def _field_rules(data: dict, where: str) -> tuple[FieldRule, ...]:
    table = _table(data, "fields", {"rules"}, where)
    rules = table.get("rules", [])
    if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
        raise ConfigError(f"{where}: fields.rules must be an array of tables")
    return tuple(_field_rule(rule, where) for rule in rules)


def _orphans(data: dict, where: str) -> OrphanOpts:
    table = _table(data, "orphans", ORPHAN_KEYS, where)
    depth = _integer(table, "folder_depth", 3, 1, "orphans", where)
    grace = _integer(table, "grace_days", 0, 0, "orphans", where)
    return OrphanOpts(
        scope=_globs(table, "scope", (), where),
        catalog=_globs(table, "catalog", (), where),
        exempt=_globs(table, "exempt", (), where),
        exempt_names=_globs(table, "exempt_names", (), where),
        unit=_choice(table.get("unit", "file"), ("file", "folder"), "[orphans] unit", where),
        folder_depth=depth,
        grace_days=grace,
    )


def _size(data: dict, where: str) -> SizeOpts:
    table = _table(data, "size", SIZE_KEYS, where)
    return SizeOpts(
        warn_chars=_integer(table, "warn_chars", 30_000, 1, "size", where),
        high_chars=_integer(table, "high_chars", 50_000, 1, "size", where),
        max_line_chars=_integer(table, "max_line_chars", 2_000, 1, "size", where),
        map_budget_chars=_integer(table, "map_budget_chars", 24_000, 1, "size", where),
        maps=_globs(table, "maps", (), where),
        exclude=_globs(table, "exclude", (), where),
    )


def _stale(data: dict, where: str) -> StaleOpts:
    table = _table(data, "stale", {"match", "days", "field"}, where)
    name = table.get("field", "updated")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{where}: [stale] field must be a key name")
    return StaleOpts(
        match=_globs(table, "match", (), where),
        days=_integer(table, "days", 14, 1, "stale", where),
        field=name,
    )


def _read(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config {path.name}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name}: {exc}") from exc


def load_config(config_path: Path | None, root_arg: Path | None, cwd: Path) -> Config:
    """Resolve the profile: --config, then discovery from the root upward, then built-ins."""
    start = (root_arg or cwd).resolve()
    if config_path is not None and not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    found = config_path.resolve() if config_path else discover(start)
    data = _read(found) if found else {}
    where = found.name if found else "built-in profile"
    top = {"version", "root", "include", "exclude", "frozen", "frozen_manifests"}
    top |= {"max_read_chars", "links", "fail_on", "format"}
    allowed = {"checks", "links_opts", "orphans", "fields", "size", "stale", "per-path-ignores"}
    allowed |= {"find", "index", "eval"}
    unknown = sorted(set(data) - top - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")
    if data.get("version", 1) != 1:
        raise ConfigError(f"{where}: unsupported version")
    root_value = data.get("root", ".")
    if not isinstance(root_value, str):
        raise ConfigError(f"{where}: root must be a string")
    if root_arg is not None:
        root = start
    else:
        root = ((found.parent if found else cwd) / root_value).resolve()
    options = _link_opts(data, where)
    max_read = data.get("max_read_chars", 2_000_000)
    if not isinstance(max_read, int) or isinstance(max_read, bool) or max_read < 1:
        raise ConfigError(f"{where}: max_read_chars must be a positive integer")
    return Config(
        root=root,
        path=found,
        include=_globs(data, "include", DEFAULT_INCLUDE, where),
        exclude=_globs(data, "exclude", DEFAULT_EXCLUDE, where),
        frozen=_globs(data, "frozen", (), where),
        frozen_manifests=_globs(data, "frozen_manifests", (), where),
        orphans=_orphans(data, where),
        field_rules=_field_rules(data, where),
        size=_size(data, where),
        stale=_stale(data, where),
        find=data.get("find", {}),
        index=data.get("index", {}),
        eval=data.get("eval", {}),
        max_read_chars=max_read,
        links=_link_styles(data, where),
        opts=options,
        checks=_checks(data, where),
        ignores=_ignores(data, where),
        fail_on=_choice(data.get("fail_on", "never"), FAIL_ON, "fail_on", where),
        format=_choice(data.get("format", "text"), FORMATS, "format", where),
    )
