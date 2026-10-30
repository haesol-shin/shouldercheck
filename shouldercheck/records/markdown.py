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
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?[ \t]*$")
TRAILING_HASHES = re.compile(r"[ \t]+#+$")
WIKI = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
HTML_ID = re.compile(r"""<[A-Za-z][^<>]*?\b(?:id|name)\s*=\s*["']([^"']+)["']""")
PATHISH = re.compile(r"^[^\s`]{3,300}$")
FRONT_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$")
FRONT_ITEM = re.compile(r"^\s+-\s+(.*?)\s*$")
TRAILING_COMMENT = re.compile(r"\s+#.*$")
HEAD_FIELD = re.compile(r"^\s*(?:[-*]\s+)?\**([A-Za-z][\w-]*)\**\s*:\s*(.*?)\s*$")
HEAD_SEPARATOR = re.compile(r"\s·\s")
HEAD_LINES = 100


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


@dataclass(frozen=True)
class Heading:
    line: int
    text: str


@dataclass(frozen=True)
class Wiki:
    """`[[name#heading|label]]`; name is empty for a same-file heading link."""

    line: int
    name: str
    heading: str | None = None


@dataclass(frozen=True)
class CodeSpan:
    line: int
    text: str


@dataclass(frozen=True)
class BodyField:
    """A `key: value` pair `offset` lines below the end of the front matter."""

    offset: int
    key: str
    value: str


@dataclass
class ParsedDoc:
    body_start: int = 0
    links: list[Link] = field(default_factory=list)
    ignores: list[Ignore] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    wikis: list[Wiki] = field(default_factory=list)
    code_spans: list[CodeSpan] = field(default_factory=list)
    html_ids: set[str] = field(default_factory=set)
    front: dict[str, str | list[str]] = field(default_factory=dict)
    front_lines: dict[str, int] = field(default_factory=dict)
    head_fields: list[BodyField] = field(default_factory=list)


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


def find_headings(text: str, line_no: int) -> list[Heading]:
    match = HEADING.match(text)
    if not match:
        return []
    return [Heading(line_no, TRAILING_HASHES.sub("", match.group(1) or "").strip())]


def find_wikis(text: str, line_no: int) -> list[Wiki]:
    found = []
    for match in WIKI.finditer(text):
        inner = match.group(1).replace("\\|", "|").partition("|")[0]
        name, has_heading, heading = inner.partition("#")
        name = name.strip()
        if name or has_heading:
            found.append(Wiki(line_no, name, heading.strip() if has_heading else None))
    return found


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _inline_list(value: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    quote = ""
    for char in value[1:-1]:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
        elif char in "\"'":
            quote = char
        elif char == ",":
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    items.append("".join(current).strip())
    return [item for item in items if item]


def parse_front_matter(lines: list[str]) -> tuple[dict[str, str | list[str]], dict[str, int]]:
    """Minimal YAML: `key: value`, `key: [a, "b c"]`, and `key:` followed by `- item` lines.

    `lines` are the lines between the `---` fences; keys map to 1-based line numbers
    counted from the first fence.
    """
    values: dict[str, str | list[str]] = {}
    numbers: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = FRONT_KEY.match(line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2)
        numbers[key] = index + 2
        if raw.startswith("[") and raw.endswith("]"):
            values[key] = _inline_list(raw)
        elif raw:
            values[key] = _unquote(TRAILING_COMMENT.sub("", raw) if raw[0] not in "\"'" else raw)
        else:
            items = []
            for follow in lines[index + 1 :]:
                item = FRONT_ITEM.match(follow)
                if not item:
                    break
                items.append(_unquote(item.group(1).strip()))
            values[key] = items or ""
    return values, numbers


def find_head_fields(lines: list[str], start: int) -> list[BodyField]:
    """`key: value` pairs in the first lines of the body, also `a: x · b: y` on one line."""
    found = []
    for offset, line in enumerate(lines[start : start + HEAD_LINES]):
        for segment in HEAD_SEPARATOR.split(line):
            match = HEAD_FIELD.match(segment)
            if match:
                found.append(BodyField(offset, match.group(1), match.group(2)))
    return found


def parse(text: str) -> ParsedDoc:
    lines = split_lines(text)
    doc = ParsedDoc(body_start=body_start(lines))
    if doc.body_start:
        doc.front, doc.front_lines = parse_front_matter(lines[1 : doc.body_start - 1])
    doc.head_fields = find_head_fields(lines, doc.body_start)
    for line_no, line in prose_lines(lines, doc.body_start):
        masked, spans = mask_inline_code(line)
        doc.links.extend(find_links(masked, line_no))
        doc.ignores.extend(find_ignores(masked, line_no))
        doc.headings.extend(find_headings(line, line_no))
        doc.wikis.extend(find_wikis(masked, line_no))
        doc.html_ids.update(HTML_ID.findall(masked))
        doc.code_spans.extend(
            CodeSpan(line_no, span.strip()) for span in spans if PATHISH.match(span.strip())
        )
    return doc
