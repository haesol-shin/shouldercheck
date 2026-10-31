"""Run `shck index`: plan, compare with the disk, then write or report."""

from dataclasses import dataclass

from shouldercheck.memory.find import InputError
from shouldercheck.memory.indexgen import Plan, build_plan, unified_diff, write_all
from shouldercheck.memory.settings import index_settings
from shouldercheck.records.config import Config
from shouldercheck.records.scan import scan_tree

SCHEMA_VERSION = 1


@dataclass
class IndexReport:
    plan: Plan
    written: list[str]
    diffs: dict[str, str]
    blocked: list[str]
    check: bool

    @property
    def exit_code(self) -> int:
        if self.blocked:
            return 3
        return int(self.check and bool(self.plan.stale))

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "files": [
                {"path": f.path, "status": f.status, "chars": len(f.text)} for f in self.plan.files
            ],
            "written": self.written,
            "map": {"chars": self.plan.map_chars, "budget": self.plan.budget},
            "shrunk": self.plan.shrunk,
            "blocked": self.blocked,
            "notes": self.plan.notes,
        }

    def render_text(self) -> str:
        lines = [self.diffs[path] for path in sorted(self.diffs)]
        for output in self.plan.files:
            verb = "wrote" if output.path in self.written else output.status
            lines.append(f"{verb:8}{output.path} ({len(output.text)} chars)")
        lines.append(f"map: {self.plan.map_chars} of {self.plan.budget} characters")
        lines += [f"note: {note}" for note in self.plan.notes]
        lines += [f"refused: {path} is hand-written; nothing was written" for path in self.blocked]
        return "\n".join(line.rstrip("\n") for line in lines) + "\n"


def run_index(cfg: Config, *, check: bool, diff: bool, adopt: bool) -> IndexReport:
    settings = index_settings(cfg)
    if not cfg.root.is_dir():
        raise InputError(f"record base not found: {cfg.root}")
    plan = build_plan(cfg, settings, scan_tree(cfg))
    blocked = [c.path for c in plan.conflicts if not (adopt and c.adoptable)]
    diffs = {}
    if diff:
        diffs = {f.path: unified_diff(cfg, f) for f in plan.files if f.status != "current"}
    written: list[str] = []
    if not check and not blocked:
        written = write_all(cfg, plan, adopt)
    return IndexReport(plan, written, diffs, blocked, check)
