"""Turn one file into searchable units: fields, weighted term counts, names and links."""

import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field

from shouldercheck.memory.defaults import MARKER
from shouldercheck.memory.settings import FindSettings
from shouldercheck.memory.tokens import norm, tokenize
from shouldercheck.records import markdown

LINK = re.compile(r"\[([^\]]*)\]\((?:<([^>]+)>|([^)\s]+))\)")
EXTERNAL = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|/|~|#)")
TITLE_LINES = 30
FIELD_LABELS = {
    "aliases": "alias",
    "title": "title",
    "tags": "tag",
    "summary": "summary",
    "name": "name",
    "body": "body",
}


@dataclass
class RawLink:
    target: str
    relation: str


@dataclass
class Unit:
    """One thing the ranker scores: a record."""

    path: str
    tier: str
    title: str
    summary: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: str = ""
    tf: dict[str, float] = field(default_factory=dict)
    length: int = 0
    names: list[tuple[str, int]] = field(default_factory=list)
    links: list[RawLink] = field(default_factory=list)


@dataclass
class Fields:
    """The six text fields of a record, before tokenising."""

    values: dict[str, str]
    title: str
    summary: str
    aliases: list[str]
    tags: list[str]
    status: str
    meta: dict[str, str | list[str]]
    lines: list[str]
    start: int


def decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def is_generated(text: str) -> bool:
    first = text.split("\n", 1)[0]
    return first.rstrip() == MARKER


def as_list(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if item]
    return [item.strip() for item in re.split(r"[,，]", value or "") if item.strip()]


def _title(meta: dict, lines: list[str], start: int, rel: str) -> str:
    named = meta.get("title")
    if isinstance(named, str) and named:
        return named
    for line in lines[start : start + TITLE_LINES]:
        if line.startswith("# "):
            return line[2:].strip()
    return posixpath.splitext(posixpath.basename(rel))[0]


def _summary(meta: dict, body: list[str]) -> str:
    summary = meta.get("summary")
    if isinstance(summary, str) and summary:
        return summary
    quote = next((ln[1:].strip() for ln in body if ln.startswith(">") and ln[1:].strip()), None)
    if quote:
        return quote
    return next((ln.strip() for ln in body if ln.strip() and not ln.startswith("#")), "")


def read_fields(rel: str, text: str) -> Fields:
    lines = markdown.split_lines(text)
    start = markdown.body_start(lines)
    meta = markdown.parse_front_matter(lines[1 : start - 1])[0] if start else {}
    body = lines[start:]
    stem = posixpath.splitext(posixpath.basename(rel))[0]
    aliases, tags = as_list(meta.get("aliases")), as_list(meta.get("tags"))
    title = _title(meta, lines, start, rel)
    summary = _summary(meta, body)
    values = {
        "aliases": " ".join(aliases),
        "title": title,
        "tags": " ".join(tags),
        "summary": str(meta.get("summary", "")),
        "name": stem.replace("-", " ").replace("_", " "),
        "body": "\n".join(body),
    }
    status = meta.get("status", "")
    return Fields(values, title, summary, aliases, tags, str(status), meta, lines, start)


def _names(rel: str, title: str, aliases: list[str]) -> list[tuple[str, int]]:
    """Exact-name keys. Kind 0: an alias or a title that is not just the file name. Kind 1: the
    file name, or a title that only repeats it."""
    stem = posixpath.splitext(posixpath.basename(rel))[0]
    stems = {norm(stem), norm(stem.replace("-", " ").replace("_", " "))}
    topic = {norm(alias) for alias in aliases}
    (stems if norm(title) in stems else topic).add(norm(title))
    topic.discard("")
    stems.discard("")
    return [(name, 0) for name in sorted(topic)] + [(name, 1) for name in sorted(stems - topic)]


def _links(fields: Fields, settings: FindSettings) -> list[RawLink]:
    found: list[RawLink] = []
    regex = settings.relations.regex
    for _, line in markdown.prose_lines(fields.lines, fields.start):
        clean = markdown.mask_inline_code(line)[0]
        for match in LINK.finditer(clean):
            target = (match.group(2) or match.group(3)).strip()
            if not target or EXTERNAL.match(target):
                continue
            before = regex.findall(clean[: match.start()]) if regex else []
            found.append(RawLink(target, before[-1] if before else ""))
    return found


def weighted_terms(
    values: dict[str, str], weights: dict[str, float]
) -> tuple[dict[str, float], int]:
    tf: Counter[str] = Counter()
    length = 0
    for name, value in values.items():
        tokens = tokenize(value)
        length += len(tokens)
        for token, count in Counter(tokens).items():
            tf[token] += weights[name] * count
    return {token: weight for token, weight in tf.items() if weight}, length


def record_unit(rel: str, text: str, settings: FindSettings) -> Unit:
    fields = read_fields(rel, text)
    tf, length = weighted_terms(fields.values, settings.weights)
    return Unit(
        path=rel,
        tier="records",
        title=fields.title,
        summary=fields.summary,
        aliases=fields.aliases,
        tags=fields.tags,
        status=fields.status,
        tf=tf,
        length=length,
        names=_names(rel, fields.title, fields.aliases),
        links=_links(fields, settings),
    )
