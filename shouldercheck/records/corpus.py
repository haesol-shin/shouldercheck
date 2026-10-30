"""All files in scope, parsed once, plus link resolution against the tree on disk."""

import posixpath
import re
from dataclasses import dataclass
from urllib.parse import unquote

from shouldercheck.records import anchors, markdown
from shouldercheck.records.config import Config
from shouldercheck.records.scan import Scan

SCHEME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]+:|//|[A-Za-z]:[\\/])")
DATED_SUFFIX = re.compile(r"^(?:v\d+|\d{6,8}|\d{4}-\d{2}-\d{2})\w*$")
EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")
GENERIC_NAMES = {"index.md", "readme.md"}


@dataclass
class Doc:
    path: str
    text: str
    parsed: markdown.ParsedDoc
    frozen: bool


@dataclass(frozen=True)
class Resolution:
    """kind: skip (external or not resolved by rule), self, file, dir, directory (not
    linkable), ambiguous (several wiki candidates), missing."""

    kind: str
    path: str = ""
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ref:
    """One reference from a file to another, in any enabled link style."""

    style: str
    line: int
    target: str
    resolution: Resolution
    fragment: str | None = None
    label_like: bool = False


def _fold(text: str) -> str:
    return text.casefold()


def _strip_md(name: str) -> str:
    return name[:-3] if name.lower().endswith(".md") else name


class Corpus:
    def __init__(self, cfg: Config, scan: Scan, docs: dict[str, Doc]) -> None:
        self.cfg = cfg
        self.scan = scan
        self.docs = docs
        self._by_name: dict[str, list[str]] = {}
        self._md_stems: dict[str, list[str]] = {}
        for rel in sorted(scan.all_files):
            name = posixpath.basename(rel)
            self._by_name.setdefault(name, []).append(rel)
            if name.lower().endswith(".md"):
                self._md_stems.setdefault(_fold(_strip_md(name)), []).append(rel)
        self._titles: dict[str, list[str]] | None = None
        self._ids: dict[str, set[str]] = {}
        self._refs: dict[str, list[Ref]] = {}

    def resolve(self, doc_path: str, target: str) -> Resolution:
        """Resolve a link target relative to the file's own folder; no root fallback."""
        if SCHEME.match(target) or target.startswith(("/", "~")):
            return Resolution("skip")
        path = unquote(target.partition("#")[0])
        if not path:
            return Resolution("self", doc_path)
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(doc_path), path))
        if joined == ".." or joined.startswith("../"):
            return Resolution("missing")
        if joined in self.scan.all_files:
            return Resolution("file", joined)
        if joined in self.scan.all_dirs:
            return Resolution("dir" if self.cfg.opts.link_dirs else "directory", joined)
        return Resolution("missing", joined)

    def resolve_wiki(self, doc_path: str, name: str) -> Resolution:
        """Resolve `[[name]]` by stem, title or path; two candidates are never guessed."""
        name = name.strip()
        if not name:
            return Resolution("self", doc_path)
        mode = self.cfg.opts.wiki_resolve
        if EXTENSION.search(name) and not name.lower().endswith(".md"):
            found = self._attachments(name)
        elif mode == "path":
            target = posixpath.normpath(_strip_md(name) + ".md")
            found = [target] if target in self.scan.all_files else []
        else:
            found = self._notes(_strip_md(name), mode)
        if len(found) == 1:
            return Resolution("file", found[0])
        return Resolution("ambiguous" if found else "missing", "", tuple(found))

    def _attachments(self, name: str) -> list[str]:
        tail = "/" + name.lstrip("/")
        return [
            p for p in self._by_name.get(posixpath.basename(name), []) if ("/" + p).endswith(tail)
        ]

    def _notes(self, key: str, mode: str) -> list[str]:
        folded = _fold(key)
        if "/" in folded:
            tail = "/" + folded.lstrip("/")
            return [
                p
                for paths in self._md_stems.values()
                for p in paths
                if ("/" + _fold(_strip_md(p))).endswith(tail)
            ]
        if mode == "title":
            return self._title_index().get(folded) or self._md_stems.get(folded, [])
        return self._md_stems.get(folded, [])

    def _title_index(self) -> dict[str, list[str]]:
        if self._titles is None:
            self._titles = {}
            for doc in self.docs.values():
                if doc.parsed.headings:
                    title = _fold(anchors.plain(doc.parsed.headings[0].text).strip())
                    self._titles.setdefault(title, []).append(doc.path)
        return self._titles

    def resolve_backtick(self, doc_path: str, text: str) -> str | None:
        """An inline-code path that names an existing file; bare generic names never resolve."""
        path = LINE_SUFFIX.sub("", text)
        if "/" not in path and path.lower() in GENERIC_NAMES:
            return None
        if SCHEME.match(path) or path.startswith(("/", "~", "-", "$")):
            return None
        for base in (posixpath.dirname(doc_path), ""):
            joined = posixpath.normpath(posixpath.join(base, path))
            if joined in self.scan.all_files:
                return joined
        return None

    def anchor_ids(self, path: str) -> set[str] | None:
        """Fragments offered by a Markdown file in scope; None when it cannot be checked."""
        doc = self.docs.get(path)
        if doc is None or not path.lower().endswith(".md"):
            return None
        if path not in self._ids:
            self._ids[path] = anchors.heading_ids(doc.parsed, self.cfg.opts)
        return self._ids[path]

    def refs(self, doc: Doc) -> list[Ref]:
        """References of a file in every enabled link style, resolved once."""
        if doc.path not in self._refs:
            self._refs[doc.path] = self._collect_refs(doc)
        return self._refs[doc.path]

    def _collect_refs(self, doc: Doc) -> list[Ref]:
        styles = self.cfg.links
        found: list[Ref] = []
        if "markdown" in styles:
            for link in doc.parsed.links:
                path, has_fragment, fragment = link.target.partition("#")
                found.append(
                    Ref(
                        "markdown",
                        link.line,
                        link.target,
                        self.resolve(doc.path, link.target),
                        fragment if has_fragment else None,
                        _is_label_like(link, path),
                    )
                )
        if "wiki" in styles:
            for wiki in doc.parsed.wikis:
                shown = f"[[{wiki.name}{'#' + wiki.heading if wiki.heading is not None else ''}]]"
                label = "/" not in wiki.name and not EXTENSION.search(wiki.name)
                found.append(
                    Ref(
                        "wiki",
                        wiki.line,
                        shown,
                        self.resolve_wiki(doc.path, wiki.name),
                        wiki.heading,
                        label,
                    )
                )
        if "backtick" in styles:
            for span in doc.parsed.code_spans:
                found.append(self._backtick_ref(doc.path, span))
        return [ref for ref in found if ref.resolution.kind != "skip"]

    def _backtick_ref(self, doc_path: str, span: markdown.CodeSpan) -> Ref:
        resolved = self.resolve_backtick(doc_path, span.text)
        if resolved:
            return Ref("backtick", span.line, span.text, Resolution("file", resolved))
        path = LINE_SUFFIX.sub("", span.text)
        pathlike = path.lower().endswith(".md") and not SCHEME.match(path)
        generic = "/" not in path and path.lower() in GENERIC_NAMES
        kind = "missing" if pathlike and not generic else "skip"
        return Ref("backtick", span.line, span.text, Resolution(kind))

    def hint_for(self, target: str) -> str | None:
        """`moved?` for a unique same-name file, `renamed?` for a unique dated or versioned one."""
        path = unquote(target.partition("#")[0])
        name = posixpath.basename(posixpath.normpath(path))
        if not name:
            return None
        same = self._by_name.get(name, [])
        if len(same) == 1:
            return f"moved? {same[0]}"
        stem, ext = posixpath.splitext(name)
        renamed = [
            paths[0]
            for other, paths in self._by_name.items()
            if len(paths) == 1 and self._is_renamed(stem, ext, other)
        ]
        return f"renamed? {renamed[0]}" if len(renamed) == 1 else None

    @staticmethod
    def _is_renamed(stem: str, ext: str, other: str) -> bool:
        other_stem, other_ext = posixpath.splitext(other)
        if other_ext != ext or len(other_stem) <= len(stem) + 1 or not other_stem.startswith(stem):
            return False
        return other_stem[len(stem)] in "-_." and bool(
            DATED_SUFFIX.match(other_stem[len(stem) + 1 :])
        )


def _is_label_like(link: markdown.Link, path: str) -> bool:
    """A parenthetical remark that parsed as a link, not a path: no slash, no extension."""
    if not link.angled and any(char.isspace() for char in link.target):
        return True
    return "/" not in path and not EXTENSION.search(posixpath.basename(path))


def build_corpus(cfg: Config, scan: Scan) -> Corpus:
    docs: dict[str, Doc] = {}
    for rel in scan.paths:
        try:
            text = (scan.root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            scan.skipped.append((rel, "unreadable"))
            continue
        docs[rel] = Doc(rel, text, markdown.parse(text), cfg.frozen(rel))
    scan.skipped.sort()
    return Corpus(cfg, scan, docs)
