"""`shck pack`: print the sections a session must read, with a receipt of what was printed.

A selector is `path` (the whole file) or `path#heading`. The receipt (selector, characters,
sha256) lets a later reader prove which text was shown without keeping the text.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from shouldercheck.records import markdown
from shouldercheck.records.config import Config

LANGUAGE = "md"
BACKTICKS = re.compile(r"`+")


class PackError(Exception):
    """A selector cannot be served, or the output would be too large (exit 2)."""


@dataclass(frozen=True)
class Piece:
    selector: str
    text: str
    chars: int
    sha256: str


def _split(selector: str) -> tuple[str, str | None]:
    path, mark, heading = selector.partition("#")
    path, heading = path.strip(), heading.strip()
    if not path or (mark and not heading):
        raise PackError(f"selector {selector!r}: expected path or path#heading")
    return path, heading if mark else None


def _file(cfg: Config, selector: str, rel: str) -> Path:
    root = cfg.root.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise PackError(f"selector {selector!r}: path leaves the record base")
    if not target.is_file():
        raise PackError(f"selector {selector!r}: no such file")
    return target


def _lines(target: Path, selector: str) -> list[str]:
    try:
        raw = target.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise PackError(f"selector {selector!r}: cannot read the file as UTF-8 ({exc})") from exc
    return markdown.split_lines(raw)


def _matches(title: str, wanted: str) -> bool:
    return title == wanted or title.startswith((wanted + " ", wanted + "("))


def _section(lines: list[str], wanted: str, selector: str) -> list[str]:
    """From the heading line to the line before the next heading of the same or a higher level."""
    headings = [
        heading
        for number, text in markdown.prose_lines(lines, markdown.body_start(lines))
        for heading in markdown.find_headings(text, number)
    ]
    found = [heading for heading in headings if _matches(heading.text, wanted)]
    if not found:
        raise PackError(f"selector {selector!r}: no heading matches")
    if len(found) > 1:
        where = ", ".join(str(heading.line) for heading in found)
        raise PackError(f"selector {selector!r}: {len(found)} headings match (lines {where})")
    first = found[0]
    end = next(
        (h.line - 1 for h in headings if h.line > first.line and h.level <= first.level),
        len(lines),
    )
    return lines[first.line - 1 : end]


def pick(cfg: Config, selector: str) -> Piece:
    rel, wanted = _split(selector)
    lines = _lines(_file(cfg, selector, rel), selector)
    if wanted is not None:
        lines = _section(lines, wanted, selector)
    # Trailing blank lines are not content: adding one must not change the receipt.
    text = "\n".join(lines).rstrip()
    return Piece(selector, text, len(text), hashlib.sha256(text.encode("utf-8")).hexdigest())


def pack(cfg: Config, selectors: tuple[str, ...], max_chars: int) -> list[Piece]:
    if not selectors:
        raise PackError("no selectors: name some, or set `selectors` in [resume]")
    pieces = [pick(cfg, selector) for selector in selectors]
    total = sum(piece.chars for piece in pieces)
    if total > max_chars:
        raise PackError(
            f"{total} characters selected, over max_chars {max_chars}; "
            "narrow the selectors or raise [resume] max_chars"
        )
    return pieces


def _fenced(text: str, info: str = "") -> str:
    # The fence must be longer than any backtick run inside, or the text would close it.
    longest = max((len(run) for run in BACKTICKS.findall(text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{info}\n{text}\n{fence}\n"


def render_text(pieces: list[Piece]) -> str:
    out = ["shck pack\n"]
    for number, piece in enumerate(pieces, 1):
        out.append(f"\n[{number}] {piece.selector}\n{_fenced(piece.text, LANGUAGE)}")
    receipt = "\n".join(f"{p.sha256}  {p.chars}  {p.selector}" for p in pieces)
    out.append(f"\nreceipt\n{_fenced(receipt, 'text')}")
    return "".join(out)


def to_json(pieces: list[Piece]) -> dict:
    return {
        "total_chars": sum(piece.chars for piece in pieces),
        "sections": [
            {"selector": p.selector, "chars": p.chars, "sha256": p.sha256, "text": p.text}
            for p in pieces
        ],
    }
