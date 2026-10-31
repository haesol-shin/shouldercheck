"""The query log: one JSONL line per `find` call, outside the record base.

The log answers one question: did the agent search before it answered? It holds the masked query
and the ranked paths, never snippets, neighbours or record text. Old day files are compressed in
place and never deleted.
"""

import gzip
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from shouldercheck import __version__
from shouldercheck.memory.find import Result
from shouldercheck.memory.settings import FindSettings, resolve_dir
from shouldercheck.memory.store import config_hash, root_hash, xdg
from shouldercheck.records.config import Config

VERSION = 1
TRUNCATED = b'{"truncated":true}\n'
MAX_FIELD = 80
UNKNOWN = "unknown"


def log_dir(cfg: Config, settings: FindSettings) -> Path:
    default = xdg("XDG_STATE_HOME", ".local/state") / "shck" / root_hash(cfg.root) / "queries"
    return resolve_dir(settings.log.dir, cfg, default)


def identify(caller: str | None, session: str | None) -> tuple[str, str | None]:
    """The command line wins over the environment; a missing caller is `unknown`, a visible gap."""
    caller = caller or os.environ.get("SHCK_CALLER") or UNKNOWN
    session = session or os.environ.get("SHCK_SESSION") or None
    return caller, session


def make_record(
    cfg: Config,
    settings: FindSettings,
    result: Result,
    *,
    caller: str,
    session: str | None,
    scope: str,
    limit: int,
    now: datetime,
) -> dict:
    mask = settings.masker.mask
    ranked = [
        [mask(path), round(score, 4), tier]
        for path, score, tier in result.ranked[: settings.log.log_top]
    ]
    shown = [*result.hits, *result.transcript]
    return {
        "v": VERSION,
        "ts": now.replace(microsecond=0).isoformat(),
        "caller": mask(caller)[:MAX_FIELD],
        "session": mask(session)[:MAX_FIELD] if session else None,
        "query": mask(result.query),
        "scope": scope,
        "paths": None,
        "limit": limit,
        "ranked": ranked,
        "top_score": ranked[0][1] if ranked else None,
        "n_hits": len(shown),
        "index": result.index.state,
        "ms": result.ms,
        "shck": __version__,
        "config_hash": config_hash(cfg),
        "snapshot": None,
    }


def encode(record: dict, max_bytes: int) -> bytes:
    """One line within `max_bytes`: drop ranked entries from the end, then cut the query."""

    def line() -> bytes:
        return (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()

    data = line()
    while len(data) > max_bytes and record["ranked"]:
        record["ranked"].pop()
        data = line()
    while len(data) > max_bytes and record["query"]:
        excess = len(data) - max_bytes
        record["query"] = record["query"][: max(0, len(record["query"]) - max(excess // 3, 1))]
        data = line()
    return data


def _private_dirs(folder: Path) -> None:
    missing = []
    for path in (folder, *folder.parents):
        if path.exists():
            break
        missing.append(path)
    for path in reversed(missing):
        path.mkdir(mode=0o700, exist_ok=True)
        path.chmod(0o700)


def append(folder: Path, data: bytes, when: date, max_bytes_per_day: int) -> None:
    """Add one line to the day's file with a single O_APPEND write, so callers never interleave."""
    _private_dirs(folder)
    path = folder / f"{when.isoformat()}.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        size = os.fstat(fd).st_size
        if size + len(data) > max_bytes_per_day:
            if not _ends_with(path, TRUNCATED):
                os.write(fd, TRUNCATED)
            return
        os.write(fd, data)
    finally:
        os.close(fd)


def _ends_with(path: Path, marker: bytes) -> bool:
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - len(marker)))
        return handle.read() == marker


def compress_old(folder: Path, keep_days: int, today: date) -> list[Path]:
    """Gzip day files older than `keep_days` next to the original name; nothing is removed
    until the compressed copy reads back equal."""
    done = []
    cutoff = today - timedelta(days=keep_days)
    for path in sorted(folder.glob("*.jsonl")):
        try:
            day = date.fromisoformat(path.name.removesuffix(".jsonl"))
        except ValueError:
            continue
        if day < cutoff:
            try:
                done.append(_compress(path))
            except OSError:
                continue
    return done


def _compress(path: Path) -> Path:
    target = path.with_name(path.name + ".gz")
    original = path.read_bytes()
    # A second member is appended when an earlier compression of the same day exists.
    previous = target.read_bytes() if target.exists() else b""
    expected = (gzip.decompress(previous) if previous else b"") + original
    temp = target.with_name(target.name + ".tmp")
    temp.write_bytes(previous + gzip.compress(original))
    os.chmod(temp, 0o600)
    if gzip.decompress(temp.read_bytes()) != expected:
        temp.unlink()
        raise OSError(f"compressed copy of {path.name} does not match")
    os.replace(temp, target)
    path.unlink()
    return target


def log_query(
    cfg: Config,
    settings: FindSettings,
    result: Result,
    *,
    caller: str | None,
    session: str | None,
    scope: str,
    limit: int,
    now: datetime | None = None,
) -> None:
    """Append the call to the log. A failure prints one line and never fails `find`."""
    now = now or datetime.now(UTC)
    who, sid = identify(caller, session)
    try:
        record = make_record(
            cfg, settings, result, caller=who, session=sid, scope=scope, limit=limit, now=now
        )
        folder = log_dir(cfg, settings)
        append(
            folder,
            encode(record, settings.log.max_line_bytes),
            now.date(),
            settings.log.max_bytes_per_day,
        )
        compress_old(folder, settings.log.keep_days, now.date())
    except Exception as exc:
        print(f"shck: query log not written: {exc}", file=sys.stderr)
