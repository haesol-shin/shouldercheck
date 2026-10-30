"""Heading anchors: which fragments a Markdown file offers, under a chosen slug rule."""

import re
from urllib.parse import unquote

from shouldercheck.records.config import LinkOpts
from shouldercheck.records.markdown import ParsedDoc

INLINE_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
CUSTOM_ID = re.compile(r"\s*\{#([^}\s]+)\}\s*$")
FORMATTING = re.compile(r"<[^>]+>|[`*~]")


def plain(text: str) -> str:
    return FORMATTING.sub("", INLINE_LINK.sub(r"\1", text))


def github_slug(text: str) -> str:
    return re.sub(r"[^\w\- ]", "", plain(text).strip().lower()).replace(" ", "-")


def mkdocs_slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", plain(text).strip().lower())
    return re.sub(r"[-\s]+", "-", cleaned).strip("-")


def _slugger(rule: str):
    return mkdocs_slug if rule == "mkdocs" else github_slug


def heading_ids(parsed: ParsedDoc, opts: LinkOpts) -> set[str]:
    """Every fragment a link may use to reach this file."""
    ids = set(parsed.html_ids) if opts.html_ids else set()
    slug = _slugger(opts.slug)
    joiner = "_" if opts.slug == "mkdocs" else "-"
    seen: dict[str, int] = {}
    for heading in parsed.headings:
        text = heading.text
        custom = CUSTOM_ID.search(text) if opts.heading_ids else None
        if custom:
            ids.add(custom.group(1))
            continue
        if opts.slug == "obsidian":
            ids.add(" ".join(plain(text).split()))
            continue
        base = slug(text)
        count = seen.get(base, 0)
        seen[base] = count + 1
        ids.add(base if count == 0 else f"{base}{joiner}{count}")
    return ids


def has_fragment(fragment: str, ids: set[str], opts: LinkOpts) -> bool:
    """True when the fragment resolves; block ids and empty fragments are never flagged."""
    wanted = unquote(fragment).strip()
    if not wanted or wanted.startswith("^"):
        return True
    if wanted in ids:
        return True
    if opts.slug == "obsidian":
        return " ".join(wanted.split("#")[-1].split()) in ids
    return _slugger(opts.slug)(wanted) in ids
