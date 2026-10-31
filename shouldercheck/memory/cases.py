"""Case files: the failure ledger (tier A) and the probe set (tier B), one JSON object per line."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

STAGES = ("capture", "write", "trigger", "retrieve", "use")
LABELS = ("relevant", "irrelevant", "on-topic-wrong")
NONE = "none"


class CaseError(Exception):
    """A case file is unreadable or a line is invalid (exit 3)."""


@dataclass
class Case:
    id: str
    set: str  # ledger or probes
    query: str
    expect: str | None  # a record path, or None when no correct record exists
    snapshot: str | None = None
    must_contain: str | None = None
    stage: str | None = None
    must_pass: bool = False
    source_path: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    ambiguous: bool = False
    date: str | None = None

    @property
    def abstain(self) -> bool:
        return self.expect is None


@dataclass
class CaseSet:
    name: str
    path: Path
    digest: str
    cases: list[Case]

    @property
    def version(self) -> str:
        return f"{self.name}@{self.digest[:12]}"


def _text(row: dict, key: str, where: str, required: bool = False) -> str | None:
    value = row.get(key)
    if value is None:
        if required:
            raise CaseError(f"{where}: missing {key}")
        return None
    if not isinstance(value, str) or (required and not value):
        raise CaseError(f"{where}: {key} must be a string")
    return value


def _labels(row: dict, where: str) -> dict[str, str]:
    labels = row.get("labels", {})
    if not isinstance(labels, dict) or any(v not in LABELS for v in labels.values()):
        raise CaseError(f"{where}: labels must map paths to {', '.join(LABELS)}")
    return labels


def _case(row: dict, kind: str, where: str) -> Case:
    expect = _text(row, "expect", where, required=True)
    stage = _text(row, "first_failing_stage", where)
    if stage is not None and stage not in STAGES:
        raise CaseError(f"{where}: first_failing_stage must be one of {', '.join(STAGES)}")
    if kind == "ledger" and stage is None:
        raise CaseError(f"{where}: ledger case needs first_failing_stage")
    return Case(
        id=_text(row, "id", where, required=True) or "",
        set=kind,
        query=_text(row, "query", where, required=True) or "",
        expect=None if expect == NONE or row.get("abstain") is True else expect,
        snapshot=_text(row, "snapshot", where),
        must_contain=_text(row, "must_contain", where),
        stage=stage,
        must_pass=row.get("must_pass") is True,
        source_path=_text(row, "source_path", where),
        labels=_labels(row, where),
        ambiguous=row.get("ambiguous") is True,
        date=_text(row, "date", where),
        tags=[str(t) for t in row.get("tags", [])] if isinstance(row.get("tags", []), list) else [],
    )


def read_cases(path: Path, kind: str | None) -> CaseSet:
    """`kind` is ledger or probes; None reads each line as a ledger case when it names a stage."""
    try:
        data = path.read_bytes()
        lines = data.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CaseError(f"cannot read case file {path.name}: {exc}") from exc
    cases: list[Case] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        where = f"{path.name}:{number}"
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise CaseError(f"{where}: {exc}") from exc
        if not isinstance(row, dict):
            raise CaseError(f"{where}: a case is a JSON object")
        line_kind = kind or ("ledger" if "first_failing_stage" in row else "probes")
        cases.append(_case(row, line_kind, where))
    ids = [c.id for c in cases]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise CaseError(f"{path.name}: repeated case id {', '.join(repeated)}")
    return CaseSet(kind or path.stem, path, hashlib.sha256(data).hexdigest(), cases)


def freeze_state(case_set: CaseSet) -> dict | None:
    """Compare the file with its freeze record `<name>.freeze.json`, when there is one."""
    freeze = case_set.path.with_suffix(".freeze.json")
    if not freeze.is_file():
        return None
    try:
        recorded = json.loads(freeze.read_text(encoding="utf-8"))
        expected = recorded["sha256"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CaseError(f"cannot read {freeze.name}: {exc}") from exc
    return {
        "file": freeze.name,
        "match": expected == case_set.digest,
        "count": recorded.get("count"),
    }
