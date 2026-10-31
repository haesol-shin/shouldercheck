"""`shck index`: a capped root map and per-section indexes for the overflow.

Every generated file starts with the marker line. A path is written only when it is absent or
already marked, so a hand-written file at a generated path is never overwritten.
"""

import difflib
import os
import posixpath
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from shouldercheck.memory.defaults import MARKER
from shouldercheck.memory.docs import title_of
from shouldercheck.memory.settings import IndexSettings, Section
from shouldercheck.records.config import Config
from shouldercheck.records.scan import Scan

TITLE_CHARS = 80
HEAD_BYTES = 16_384
MAX_DEPTH = 3
GENERIC = "index.md"


@dataclass
class Entry:
    rel: str
    title: str
    mtime_ns: int = 0


@dataclass
class Output:
    """One generated file: its path, its text, and how it compares with the disk."""

    path: str
    text: str
    status: str = "new"  # new, stale, current, conflict
    adoptable: bool = False


@dataclass
class Plan:
    files: list[Output] = field(default_factory=list)
    map_chars: int = 0
    budget: int = 0
    shrunk: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def conflicts(self) -> list[Output]:
        return [f for f in self.files if f.status == "conflict"]

    @property
    def stale(self) -> list[Output]:
        return [f for f in self.files if f.status in ("new", "stale")]


def _read_head(path: Path) -> str | None:
    try:
        with open(path, "rb") as handle:
            return handle.read(HEAD_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None


def _is_marked(head: str) -> bool:
    return head.split("\n", 1)[0].rstrip() == MARKER


def _link(rel: str, title: str, start: str = "") -> str:
    target = posixpath.relpath(rel, start) if start else rel
    safe = title.replace("[", "(").replace("]", ")")
    return f"[{safe}](<{target}>)"


def collect(cfg: Config, settings: IndexSettings, scan: Scan) -> dict[str, list[Entry]]:
    """Markdown files per section id; the deepest section root owns a file."""
    roots = sorted(settings.sections, key=lambda s: len(s.root), reverse=True)
    owned: dict[str, list[Entry]] = {s.id: [] for s in settings.sections}
    for rel in sorted(scan.all_files):
        if not rel.lower().endswith(".md") or rel == settings.map or cfg.exclude(rel):
            continue
        if settings.exclude(rel):
            continue
        section = next((s for s in roots if rel.startswith(s.root + "/")), None)
        if section is None:
            continue
        head = _read_head(cfg.root / rel)
        if head is None or _is_marked(head):
            continue
        mtime = os.stat(cfg.root / rel).st_mtime_ns if section.order == "mtime-desc" else 0
        owned[section.id].append(Entry(rel, title_of(rel, head)[:TITLE_CHARS], mtime))
    return {sid: _ordered(entries, _by_id(settings, sid)) for sid, entries in owned.items()}


def _by_id(settings: IndexSettings, sid: str) -> Section:
    return next(s for s in settings.sections if s.id == sid)


def _ordered(entries: list[Entry], section: Section) -> list[Entry]:
    if section.order == "mtime-desc":
        return sorted(entries, key=lambda e: (-e.mtime_ns, e.rel))
    if section.order == "name-desc":
        return sorted(entries, key=lambda e: (posixpath.basename(e.rel), e.rel), reverse=True)
    return sorted(entries, key=lambda e: e.rel)


def _tree_lines(entries: list[Entry], root: str, start: str = "") -> list[str]:
    """Entries grouped by folder, one group per folder; a folder line precedes the files that
    are not at the root. The sort is stable, so the order inside a folder is kept."""
    lines: list[str] = []
    current = None
    for entry in sorted(entries, key=lambda e: posixpath.dirname(e.rel)):
        folder = posixpath.dirname(entry.rel)
        if folder != current and folder != root:
            lines.append(f"- `{_relative_to(folder, start)}/`")
        current = folder
        indent = "" if folder == root else "  "
        lines.append(f"{indent}- {_link(entry.rel, entry.title, start)}")
    return lines


def _relative_to(path: str, start: str) -> str:
    return posixpath.relpath(path, start) if start else path


def _count_lines(entries: list[Entry], section: Section) -> list[str]:
    groups: dict[str, int] = {}
    for entry in entries:
        rest = entry.rel[len(section.root) + 1 :]
        part = rest.split("/")[0] if "/" in rest else "."
        groups[part] = groups.get(part, 0) + 1
    lines = []
    for name, count in sorted(groups.items()):
        where = f"{section.root}/" if name == "." else f"{section.root}/{name}/"
        lines.append(f"- `{where}`: {count} files")
    return lines


def _section_block(
    section: Section, entries: list[Entry], allowance: int, with_index: bool, start: str = ""
) -> list[str]:
    lines = [f"## {section.title} · `{section.root}/`", ""]
    if section.note:
        lines += [f"_{section.note}_", ""]
    if section.mode == "count":
        body = _count_lines(entries, section)
        shown = body[:allowance]
        lines += shown or ["- empty"]
        hidden = len(body) - len(shown)
    else:
        shown_entries = entries[:allowance]
        if section.mode == "recent":
            lines += [f"- {_link(e.rel, e.title, start)}" for e in shown_entries] or ["- empty"]
        else:
            lines += _tree_lines(shown_entries, section.root, start) or ["- empty"]
        hidden = len(entries) - len(shown_entries)
    if hidden > 0:
        if with_index:
            target = f"{section.root}/{GENERIC}"
            lines.append(f"- _{hidden} more, see {_link(target, target, start)}_")
        else:
            lines.append(f"- _{hidden} more_")
    return [*lines, ""]


def render_map(
    cfg: Config,
    settings: IndexSettings,
    owned: dict[str, list[Entry]],
    allowances: dict[str, int],
) -> str:
    start = posixpath.dirname(settings.map)
    lines = [MARKER, f"# {settings.title}", ""]
    lines += [f"> {line}" for line in settings.header]
    lines += [""] if settings.header else []
    tops = [t for t in settings.top_files if t != settings.map and (cfg.root / t).is_file()]
    if tops:
        lines += [f"## {settings.top_title}", ""]
        for rel in tops:
            head = _read_head(cfg.root / rel) or ""
            lines.append(f"- {_link(rel, title_of(rel, head)[:TITLE_CHARS], start)}")
        lines.append("")
    for section in settings.sections:
        entries = owned[section.id]
        with_index = section.mode == "tree" and section.index == "folder"
        lines += _section_block(section, entries, allowances[section.id], with_index, start)
    return "\n".join(lines).rstrip("\n") + "\n"


def _available(section: Section, entries: list[Entry]) -> int:
    count = len(_count_lines(entries, section)) if section.mode == "count" else len(entries)
    return min(section.cap, count)


def shrink(
    cfg: Config, settings: IndexSettings, owned: dict[str, list[Entry]]
) -> tuple[str, dict[str, int], bool]:
    """Render the map within the budget: take one entry at a time from the section with the
    largest allowance, ties in turn by profile order, so no section disappears."""
    allowances = {s.id: _available(s, owned[s.id]) for s in settings.sections}
    budget = cfg.size.map_budget_chars
    text = render_map(cfg, settings, owned, allowances)
    shrunk = False
    turn = 0
    order = [s.id for s in settings.sections]
    while len(text) > budget:
        biggest = max(allowances.values())
        if biggest <= 1:
            break
        tied = [sid for sid in order if allowances[sid] == biggest]
        pick = next((sid for sid in tied if order.index(sid) >= turn), tied[0])
        allowances[pick] -= 1
        turn = (order.index(pick) + 1) % len(order)
        shrunk = True
        text = render_map(cfg, settings, owned, allowances)
    return text, allowances, shrunk


def _folder_index(
    title: str, folder: str, entries: list[Entry], level: int, budget: int, plan: Plan
) -> dict[str, str]:
    """Index of one folder; a folder over budget hands its subfolders their own index."""
    path = f"{folder}/{GENERIC}"
    header = [MARKER, f"# {title} · `{folder}/`", ""]
    full = "\n".join([*header, *_tree_lines(entries, folder, folder)]).rstrip("\n") + "\n"
    if len(full) <= budget:
        return {path: full}
    direct = [e for e in entries if posixpath.dirname(e.rel) == folder]
    subfolders: dict[str, list[Entry]] = {}
    for entry in entries:
        rest = entry.rel[len(folder) + 1 :]
        if "/" in rest:
            subfolders.setdefault(rest.split("/")[0], []).append(entry)
    lines = [f"- {_link(e.rel, e.title, folder)}" for e in direct]
    outputs: dict[str, str] = {}
    for name, members in sorted(subfolders.items()):
        sub = f"{folder}/{name}"
        if level < MAX_DEPTH:
            lines.append(
                f"- {_link(f'{sub}/{GENERIC}', f'{name}/', folder)} ({len(members)} files)"
            )
            outputs |= _folder_index(title, sub, members, level + 1, budget, plan)
        else:
            lines.append(f"- `{name}/`: {len(members)} files")
            plan.notes.append(f"size: {sub}/ has {len(members)} files below the depth limit")
    text = "\n".join([*header, *lines]).rstrip("\n") + "\n"
    if len(text) > budget:
        plan.notes.append(f"size: {path} has {len(text)} characters (budget {budget})")
    return {path: text, **outputs}


def build_plan(cfg: Config, settings: IndexSettings, scan: Scan) -> Plan:
    plan = Plan(budget=cfg.size.map_budget_chars)
    owned = collect(cfg, settings, scan)
    text, allowances, plan.shrunk = shrink(cfg, settings, owned)
    plan.map_chars = len(text)
    if plan.map_chars > plan.budget:
        plan.notes.append(f"size: {settings.map} has {plan.map_chars} (budget {plan.budget})")
    outputs = {settings.map: text}
    for section in settings.sections:
        if section.mode != "tree" or section.index != "folder":
            continue
        entries = owned[section.id]
        marked = _marked_on_disk(cfg, f"{section.root}/{GENERIC}")
        if len(entries) > allowances[section.id] or marked:
            outputs |= _folder_index(section.title, section.root, entries, 1, plan.budget, plan)
    real = dict(outputs)
    for path in _stale_section_indexes(cfg, settings, real):
        outputs[path] = _pointer(path, real, settings)
    for path, body in outputs.items():
        plan.files.append(_compare(cfg, settings, path, body))
    return plan


def _stale_section_indexes(
    cfg: Config, settings: IndexSettings, outputs: dict[str, str]
) -> list[str]:
    """Marked `index.md` files under any section root that the plan no longer contains."""
    found: set[str] = set()
    for section in settings.sections:
        top = cfg.root / section.root
        for here, dirs, names in os.walk(top):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            if GENERIC not in names:
                continue
            rel = Path(here, GENERIC).relative_to(cfg.root).as_posix()
            head = _read_head(cfg.root / rel)
            if rel not in outputs and head is not None and _is_marked(head):
                found.add(rel)
    return sorted(found)


def _pointer(path: str, outputs: dict[str, str], settings: IndexSettings) -> str:
    """One-line replacement for a generated index that no longer applies; the file is kept."""
    parent = posixpath.dirname(posixpath.dirname(path))
    while parent and f"{parent}/{GENERIC}" not in outputs:
        parent = posixpath.dirname(parent)
    target = f"{parent}/{GENERIC}" if parent else settings.map
    link = _link(target, target, posixpath.dirname(path))
    return f"{MARKER}\nNo longer in use; see {link}\n"


def _marked_on_disk(cfg: Config, rel: str) -> bool:
    head = _read_head(cfg.root / rel)
    return head is not None and _is_marked(head)


def _compare(cfg: Config, settings: IndexSettings, path: str, text: str) -> Output:
    existing = _read_head(cfg.root / path)
    if existing is None:
        return Output(path, text, "new")
    if not _is_marked(existing):
        return Output(path, text, "conflict", adoptable=path == settings.map)
    try:
        current = (cfg.root / path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return Output(path, text, "stale")
    return Output(path, text, "current" if current == text else "stale")


def unified_diff(cfg: Config, output: Output) -> str:
    try:
        old = (cfg.root / output.path).read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        old = []
    new = output.text.splitlines(keepends=True)
    diff = difflib.unified_diff(old, new, f"a/{output.path}", f"b/{output.path}")
    return "".join(diff)


def write_all(cfg: Config, plan: Plan, adopt: bool) -> list[str]:
    """Write the files that differ. All-or-nothing on conflicts: the caller checks first."""
    written = []
    for output in plan.files:
        if output.status == "conflict" and not (adopt and output.adoptable):
            continue
        if output.status == "current":
            continue
        _atomic_write(cfg.root / output.path, output.text)
        written.append(output.path)
    return written


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        else:
            os.chmod(temp, 0o644)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
