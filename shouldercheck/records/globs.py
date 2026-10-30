"""Glob matching on POSIX relative paths with `**` support."""

import re
from collections.abc import Iterable


def _class(pattern: str, start: int) -> tuple[str, int] | None:
    end = pattern.find("]", start + 2)
    if end == -1:
        return None
    body = pattern[start + 1 : end].replace("\\", "\\\\")
    if body.startswith("!"):
        body = "^" + body[1:]
    return f"[{body}]", end


def _translate(pattern: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**", i):
            i += 2
            if pattern.startswith("/", i):
                out.append("(?:[^/]+/)*")
                i += 1
            else:
                out.append(".*")
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[" and (cls := _class(pattern, i)):
            out.append(cls[0])
            i = cls[1]
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


class Globs:
    """A set of glob patterns; raises ValueError for an invalid pattern."""

    def __init__(self, patterns: Iterable[str]) -> None:
        self.patterns = tuple(patterns)
        self._compiled = []
        for pattern in self.patterns:
            try:
                self._compiled.append(re.compile(_translate(pattern) + r"\Z", re.DOTALL))
            except re.error as exc:
                raise ValueError(f"bad glob {pattern!r}: {exc}") from exc

    def __call__(self, rel: str) -> bool:
        return any(rx.match(rel) for rx in self._compiled)

    def __bool__(self) -> bool:
        return bool(self._compiled)
