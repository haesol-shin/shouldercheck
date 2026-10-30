"""Load and validate the TOML profile of one record base."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from shouldercheck.records.findings import SEVERITIES
from shouldercheck.records.globs import Globs

CONFIG_NAMES = ("shck.toml", ".shck.toml")
CHECK_NAMES = ("dead-link", "ignore-without-reason")
DEFAULT_CHECKS = {"dead-link": "error", "ignore-without-reason": "warn"}
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
class Config:
    root: Path
    path: Path | None
    include: Globs
    exclude: Globs
    frozen: Globs
    max_read_chars: int
    link_dirs: bool
    checks: dict[str, str]
    ignores: tuple[PathIgnore, ...]
    fail_on: str
    format: str

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
    top = {"version", "root", "include", "exclude", "frozen", "max_read_chars", "fail_on", "format"}
    unknown = sorted(set(data) - top - {"checks", "links_opts", "per-path-ignores"})
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
    opts = _table(data, "links_opts", {"link_dirs"}, where)
    max_read = data.get("max_read_chars", 2_000_000)
    if not isinstance(max_read, int) or isinstance(max_read, bool) or max_read < 1:
        raise ConfigError(f"{where}: max_read_chars must be a positive integer")
    return Config(
        root=root,
        path=found,
        include=_globs(data, "include", DEFAULT_INCLUDE, where),
        exclude=_globs(data, "exclude", DEFAULT_EXCLUDE, where),
        frozen=_globs(data, "frozen", (), where),
        max_read_chars=max_read,
        link_dirs=bool(opts.get("link_dirs", False)),
        checks=_checks(data, where),
        ignores=_ignores(data, where),
        fail_on=_choice(data.get("fail_on", "never"), FAIL_ON, "fail_on", where),
        format=_choice(data.get("format", "text"), FORMATS, "format", where),
    )
