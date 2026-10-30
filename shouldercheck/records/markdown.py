"""Line-level Markdown parsing: what is prose, what is code, and which links the prose holds."""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])(?:\s|$)")
QUOTE_PREFIX = re.compile(r"^(?:\s{0,3}>\s?)+")
ANGLE_TAIL = re.compile(r"""^(?:"[^"]*"|'[^']*'|\([^)]*\))?$""")
FENCE_OPEN = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
TITLE_TAIL = re.compile(r"""^(\S+)\s+(?:"[^"]*"|'[^']*'|\([^)]*\))$""")
IGNORE = re.compile(
    r"<!--\s*shck:\s*ignore\s+([A-Za-z][\w-]*(?:\s*,\s*[A-Za-z][\w-]*)*)"
    r'(?:\s+reason\s*=\s*"([^"]*)")?\s*-->'
)
UNESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")


@dataclass(frozen=True)
class Link:
    line: int
    target: str
    angled: bool = False


@dataclass(frozen=True)
class Ignore:
    line: int
    checks: tuple[str, ...]
    reason: str | None


@dataclass
class ParsedDoc:
    body_start: int = 0
    links: list[Link] = field(default_factory=list)
    ignores: list[Ignore] = field(default_factory=list)


def split_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def body_start(lines: list[str]) -> int:
    """Index of the first line after front matter, or 0 when there is none."""
    if lines and lines[0].rstrip() == "---":
        for index in range(1, len(lines)):
            if lines[index].rstrip() in ("---", "..."):
                return index + 1
    return 0


def _indent(line: str) -> int:
    width = 0
    for char in line:
        if char == " ":
            width += 1
        elif char == "\t":
            width += 4
        else:
            break
    return width


def _fence_opener(line: str, in_list: bool) -> tuple[str, int] | None:
    match = FENCE_OPEN.match(line)
    if not match:
        return None
    if _indent(match.group(1)) >= 4 and not in_list:
        return None
    marker = match.group(2)
    if marker[0] == "`" and "`" in match.group(3):
        return None
    return marker[0], len(marker)


def _closes_fence(line: str, fence: tuple[str, int]) -> bool:
    stripped = line.strip()
    return len(stripped) >= fence[1] and stripped == fence[0] * len(stripped)


def prose_lines(lines: list[str], start: int) -> Iterator[tuple[int, str]]:
    """Yield (1-based line number, text) for lines outside fenced and indented code."""
    fence: tuple[str, int] | None = None
    in_list = False
    after_blank = True
    for index in range(start, len(lines)):
        line = lines[index]
        bare = QUOTE_PREFIX.sub("", line)
        if fence:
            if _closes_fence(bare, fence):
                fence = None
            continue
        fence = _fence_opener(bare, in_list)
        if fence:
            after_blank = False
            continue
        if not bare.strip():
            after_blank = True
            continue
        indent = _indent(bare)
        if indent >= 4 and not in_list and after_blank:
            continue
        if LIST_MARKER.match(bare):
            in_list = True
        elif indent == 0:
            in_list = False
        after_blank = False
        yield index + 1, line


def mask_inline_code(text: str) -> tuple[str, list[str]]:
    """Blank out inline code spans (same length) and return their contents."""
    out: list[str] = []
    spans: list[str] = []
    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if char == "\\" and i + 1 < n and text[i + 1] == "`":
            out.append(text[i : i + 2])
            i += 2
            continue
        if char != "`":
            out.append(char)
            i += 1
            continue
        run_end = i
        while run_end < n and text[run_end] == "`":
            run_end += 1
        close = _closing_run(text, run_end, run_end - i)
        if close < 0:
            out.append(text[i:run_end])
            i = run_end
            continue
        spans.append(text[run_end:close])
        out.append(" " * (close + (run_end - i) - i))
        i = close + (run_end - i)
    return "".join(out), spans


def _closing_run(text: str, start: int, length: int) -> int:
    k, n = start, len(text)
    while k < n:
        if text[k] != "`":
            k += 1
            continue
        end = k
        while end < n and text[end] == "`":
            end += 1
        if end - k == length:
            return k
        k = end
    return -1


def _has_opener(text: str, close: int) -> bool:
    depth = 1
    for k in range(close - 1, -1, -1):
        if text[k] == "]" and (k == 0 or text[k - 1] != "\\"):
            depth += 1
        elif text[k] == "[" and (k == 0 or text[k - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return True
    return False


def _parse_target(text: str, pos: int) -> tuple[str, bool, int] | None:
    """Parse the part after `](`. Returns (target, angled, index after the closing paren)."""
    n = len(text)
    while pos < n and text[pos] in " \t":
        pos += 1
    if pos < n and text[pos] == "<":
        end = text.find(">", pos + 1)
        close = text.find(")", end) if end >= 0 else -1
        if close < 0 or not ANGLE_TAIL.match(text[end + 1 : close].strip()):
            return None
        return text[pos + 1 : end], True, close + 1
    depth, k = 0, pos
    while k < n:
        char = text[k]
        if char == "\\" and k + 1 < n:
            k += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
        k += 1
    else:
        return None
    raw = text[pos:k].strip()
    titled = TITLE_TAIL.match(raw)
    return (titled.group(1) if titled else raw), False, k + 1


def find_links(text: str, line_no: int) -> list[Link]:
    """Inline links `[text](target)` in one line already stripped of inline code."""
    links: list[Link] = []
    i = 0
    while True:
        j = text.find("](", i)
        if j < 0:
            return links
        parsed = _parse_target(text, j + 2) if _has_opener(text, j) else None
        if parsed is None:
            i = j + 2
            continue
        target, angled, i = parsed
        if target:
            links.append(Link(line_no, UNESCAPE.sub(r"\1", target), angled))


def find_ignores(text: str, line_no: int) -> list[Ignore]:
    found = []
    for match in IGNORE.finditer(text):
        checks = tuple(name.strip() for name in match.group(1).split(","))
        found.append(Ignore(line_no, checks, (match.group(2) or "").strip() or None))
    return found


def parse(text: str) -> ParsedDoc:
    lines = split_lines(text)
    doc = ParsedDoc(body_start=body_start(lines))
    for line_no, line in prose_lines(lines, doc.body_start):
        masked, _ = mask_inline_code(line)
        doc.links.extend(find_links(masked, line_no))
        doc.ignores.extend(find_ignores(masked, line_no))
    return doc
