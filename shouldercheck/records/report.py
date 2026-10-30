"""Run the checks and render the result as text or JSON."""

from collections import Counter
from dataclasses import dataclass, field

from shouldercheck.records.checks import CHECKS
from shouldercheck.records.config import Config
from shouldercheck.records.corpus import build_corpus
from shouldercheck.records.findings import SEVERITIES, Finding, clip, severity_rank
from shouldercheck.records.scan import scan_tree
from shouldercheck.records.suppress import IGNORE_CHECK, partition, reasonless_ignores

SCHEMA_VERSION = 1


@dataclass
class Report:
    root: str
    config: str | None
    files: int = 0
    frozen_files: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None
    findings: list[Finding] = field(default_factory=list)
    frozen: Counter[str] = field(default_factory=Counter)
    frozen_in: dict[str, int] = field(default_factory=dict)
    suppressed: Counter[str] = field(default_factory=Counter)
    levels: dict[str, str] = field(default_factory=dict)

    def by_check(self) -> dict[str, dict[str, int]]:
        table: dict[str, dict[str, int]] = {}
        for finding in self.findings:
            row = table.setdefault(finding.check, {})
            row[finding.severity] = row.get(finding.severity, 0) + 1
        for check, count in self.frozen.items():
            table.setdefault(check, {})["frozen"] = count
            table[check]["frozen_files"] = self.frozen_in[check]
        for check, count in self.suppressed.items():
            table.setdefault(check, {})["suppressed"] = count
        return dict(sorted(table.items()))

    def exit_code(self, fail_on: str) -> int:
        if self.error:
            return 3
        if fail_on == "never":
            return 0
        floor = severity_rank(fail_on)
        return int(any(severity_rank(f.severity) >= floor for f in self.findings))

    def to_json(self) -> dict[str, object]:
        counts = Counter(f.severity for f in self.findings)
        scan: dict[str, object] = {
            "files": self.files,
            "frozen": self.frozen_files,
            "skipped": [{"path": clip(p), "reason": r} for p, r in self.skipped],
        }
        if self.error:
            scan["error"] = self.error
        return {
            "schema_version": SCHEMA_VERSION,
            "root": self.root,
            "config": self.config,
            "scan": scan,
            "summary": {
                **{sev: counts.get(sev, 0) for sev in reversed(SEVERITIES)},
                "suppressed": sum(self.suppressed.values()),
                "by_check": self.by_check(),
            },
            "findings": [f.to_json() for f in self.findings],
        }

    def render_text(self, max_rows: int) -> str:
        head = f"shck check  root={self.root}  files={self.files}"
        head += f" (frozen {self.frozen_files}, skipped {len(self.skipped)})"
        lines = [head + f"  config={self.config or 'built-in'}"]
        if self.error:
            lines.append(f"error: {self.error}")
        groups = self._groups()
        for (check, severity), rows in groups.items():
            lines.append(self._summary_line(check, severity, len(rows)))
        for (check, severity), rows in groups.items():
            if not rows:
                continue
            lines += ["", f"== {check} ({severity}) {len(rows)}"]
            lines += [_row(f) for f in rows[:max_rows]]
            if len(rows) > max_rows:
                lines.append(f"... {len(rows) - max_rows} more (see --format json)")
        return "\n".join(lines) + "\n"

    def _groups(self) -> dict[tuple[str, str], list[Finding]]:
        groups: dict[tuple[str, str], list[Finding]] = {}
        for finding in self.findings:
            groups.setdefault((finding.check, finding.severity), []).append(finding)
        for check in {*self.frozen, *self.suppressed}:
            if not any(key[0] == check for key in groups) and check in self.levels:
                groups[(check, self.levels[check])] = []
        return dict(sorted(groups.items(), key=lambda kv: (kv[0][0], -severity_rank(kv[0][1]))))

    def _summary_line(self, check: str, severity: str, count: int) -> str:
        line = f"{severity:<9} {check:<22} {count:<5}"
        notes = []
        if self.frozen.get(check):
            notes.append(f"frozen: {self.frozen[check]} in {self.frozen_in[check]} files")
        if self.suppressed.get(check):
            notes.append(f"suppressed: {self.suppressed[check]}")
        return f"{line} ({'; '.join(notes)})" if notes else line.rstrip()


def _row(finding: Finding) -> str:
    where = finding.path + (f":{finding.line}" if finding.line else "")
    parts = [where, finding.target or finding.message]
    if finding.target:
        parts.append(finding.message)
    if finding.hint:
        parts.append(finding.hint)
    return clip("  ".join(parts))


def run_check(cfg: Config, only: set[str] | None = None, skip: set[str] | None = None) -> Report:
    report = Report(str(cfg.root), cfg.display_path)
    if not cfg.root.is_dir():
        report.error = "root is not a directory"
        return report
    scan = scan_tree(cfg)
    corpus = build_corpus(cfg, scan)
    wanted = {
        name
        for name in (*CHECKS, IGNORE_CHECK)
        if cfg.severity(name) and (not only or name in only) and name not in (skip or set())
    }
    findings = [f for name, run in CHECKS.items() if name in wanted for f in run(corpus)]
    if IGNORE_CHECK in wanted:
        findings += reasonless_ignores(corpus, cfg)
    result = partition(findings, corpus, cfg)
    report.files = len(corpus.docs)
    report.frozen_files = sum(doc.frozen for doc in corpus.docs.values())
    report.skipped = scan.skipped
    report.findings = result.listed
    report.frozen = result.frozen
    report.frozen_in = {check: len(paths) for check, paths in result.frozen_paths.items()}
    report.suppressed = result.suppressed
    report.levels = {name: cfg.checks[name] for name in wanted}
    return report
