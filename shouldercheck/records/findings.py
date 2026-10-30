"""The finding model shared by every check."""

from dataclasses import dataclass

SEVERITIES = ("candidate", "warn", "error")
CLIP = 200


def severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity)


def clip(text: str) -> str:
    return text if len(text) <= CLIP else text[: CLIP - 3] + "..."


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    path: str
    message: str
    line: int | None = None
    target: str | None = None
    hint: str | None = None

    @property
    def fingerprint(self) -> str:
        # No line number: a baseline must survive edits above the finding.
        return f"{self.check}|{self.path}|{self.target or ''}"

    def sort_key(self) -> tuple[str, str, int, str]:
        return (self.check, self.path, self.line or 0, self.target or "")

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {
            "check": self.check,
            "severity": self.severity,
            "path": clip(self.path),
            "line": self.line,
            "target": None if self.target is None else clip(self.target),
            "message": clip(self.message),
            "hint": None if self.hint is None else clip(self.hint),
            "fingerprint": clip(self.fingerprint),
        }
        return data
