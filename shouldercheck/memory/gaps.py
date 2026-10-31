"""`shck gaps`: which facts from a source have no record, by plain string coverage.

No model: the facts file comes from an extractor outside shck, and a fact is `present` when one
blank-line-separated block of a candidate record holds most of its keywords.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from shouldercheck import __version__
from shouldercheck.memory.cases import CaseError
from shouldercheck.memory.evalrun import SCHEMA_VERSION
from shouldercheck.memory.find import rank_records
from shouldercheck.memory.settings import FindSettings, GapsSettings
from shouldercheck.memory.stats import wilson
from shouldercheck.memory.store import config_hash
from shouldercheck.memory.trees import Trees
from shouldercheck.records.config import Config
from shouldercheck.records.globs import Globs

KINDS = ("decision", "correction", "rule", "state")
STATUSES = ("present", "weak", "absent")
OWNER_STATUSES = (*STATUSES, "invalid-fact")
QUOTE_CHARS = 200
BLANK = re.compile(r"\n[ \t]*\n")


@dataclass
class Fact:
    id: str
    text: str
    source: str
    keywords: list[str]
    kind: str | None = None
    quote: str | None = None
    expect: str | None = None

    @property
    def source_file(self) -> str:
        return self.source.split("#", 1)[0]


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def read_facts(path: Path) -> tuple[list[Fact], str]:
    try:
        data = path.read_bytes()
        lines = data.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CaseError(f"cannot read facts file {path.name}: {exc}") from exc
    facts = []
    for number, line in enumerate(lines, 1):
        if line.strip():
            facts.append(_fact(line, f"{path.name}:{number}"))
    ids = [f.id for f in facts]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise CaseError(f"{path.name}: repeated fact id {', '.join(repeated)}")
    return facts, hashlib.sha256(data).hexdigest()


def _fact(line: str, where: str) -> Fact:
    try:
        row = json.loads(line)
    except ValueError as exc:
        raise CaseError(f"{where}: {exc}") from exc
    if not isinstance(row, dict):
        raise CaseError(f"{where}: a fact is a JSON object")
    for key in ("id", "text", "source"):
        if not isinstance(row.get(key), str) or not row[key]:
            raise CaseError(f"{where}: {key} must be a non-empty string")
    words = row.get("keywords")
    if not isinstance(words, list) or not words or not all(isinstance(w, str) and w for w in words):
        raise CaseError(f"{where}: keywords must be a non-empty list of strings")
    kind, quote, expect = row.get("kind"), row.get("quote"), row.get("expect")
    if kind is not None and kind not in KINDS:
        raise CaseError(f"{where}: kind must be one of {', '.join(KINDS)}")
    if quote is not None and (not isinstance(quote, str) or len(quote) > QUOTE_CHARS):
        raise CaseError(f"{where}: quote must be a string of at most {QUOTE_CHARS} characters")
    if expect is not None and not isinstance(expect, str):
        raise CaseError(f"{where}: expect must be a string")
    return Fact(row["id"], row["text"], row["source"], words, kind, quote, expect)


def _blocks(text: str) -> list[tuple[int, str]]:
    """Blank-line-separated blocks with the 1-based line each one starts on."""
    blocks, position, line = [], 0, 1
    for match in BLANK.finditer(text):
        blocks.append((line, text[position : match.start()]))
        line += text.count("\n", position, match.end())
        position = match.end()
    blocks.append((line, text[position:]))
    return blocks


def coverage(text: str, keywords: list[str]) -> tuple[float, int, bool]:
    """(largest share of keywords inside one block, 1-based line of that block, all in file)."""
    folded = [_fold(word) for word in keywords]
    best, best_line = 0.0, 1
    for line, block in _blocks(text):
        text_block = _fold(block)
        share = sum(word in text_block for word in folded) / len(folded)
        if share > best:
            best, best_line = share, line
    whole = _fold(text)
    return best, best_line, all(word in whole for word in folded)


def classify(shares: list[tuple[float, bool]], options: GapsSettings, expect_ok: list[bool]) -> str:
    """present needs a candidate that matches `expect` (when set); a strong match elsewhere
    only counts as weak."""
    strong = [s for (s, _), ok in zip(shares, expect_ok, strict=True) if ok]
    if strong and max(strong) >= options.present:
        return "present"
    if any(share >= options.weak or whole for share, whole in shares):
        return "weak"
    return "absent"


def _candidates(index, fact: Fact, count: int) -> list[tuple[str, float]]:
    seen: dict[str, float] = {}
    for query in (" ".join(fact.keywords), fact.text):
        ranked = [r for r in rank_records(index, query) if r.doc.path != fact.source_file]
        for item in ranked[:count]:
            seen.setdefault(item.doc.path, item.score)
    return list(seen.items())


def analyse(
    cfg: Config,
    find: FindSettings,
    options: GapsSettings,
    facts: list[Fact],
    digest: str,
    name: str,
    *,
    git_dir: Path | None,
    snapshot_commit: str | None,
    candidates: int | None,
) -> dict:
    trees = Trees(cfg, find, git_dir)
    rows = []
    try:
        index, _ = trees.open(snapshot_commit)
        count = candidates or options.candidates
        for fact in facts:
            rows.append(_row(trees, index, fact, options, count, snapshot_commit))
        info = trees.info()
    finally:
        trees.close()
    summary = {status: sum(r["status"] == status for r in rows) for status in STATUSES}
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "gaps",
        "finder": {"shck": __version__, "config_hash": config_hash(cfg)},
        "facts_file": {"file": name, "sha256": digest, "count": len(facts)},
        "trees": info,
        "thresholds": {"present": options.present, "weak": options.weak, "candidates": count},
        "summary": {"n": len(rows), **summary},
        "facts": rows,
    }


def _row(trees: Trees, index, fact: Fact, options: GapsSettings, count: int, commit) -> dict:
    found = []
    shares: list[tuple[float, bool]] = []
    matches = Globs([fact.expect]) if fact.expect else None
    for path, score in _candidates(index, fact, count):
        text = trees.read(commit, path) or ""
        share, line, whole = coverage(text, fact.keywords)
        shares.append((share, whole))
        found.append(
            {"path": path, "score": round(score, 4), "coverage": round(share, 4), "line": line}
        )
    expect_ok = [matches is None or matches(c["path"]) for c in found]
    status = classify(shares, options, expect_ok)
    best = max((c["coverage"] for c in found), default=0.0)
    row = {
        "id": fact.id,
        "status": status,
        "coverage": best,
        "kind": fact.kind,
        "candidates": found,
    }
    if matches is not None and status != "present" and any(s >= options.present for s, _ in shares):
        row["expect_missing"] = True
    return row


def audit_template(rows: list[dict], size: int, seed: str) -> list[dict]:
    """Fact ids ordered by sha256(seed:id); the owner fills `owner` by hand."""
    ordered = sorted(rows, key=lambda r: hashlib.sha256(f"{seed}:{r['id']}".encode()).hexdigest())
    return [{"id": r["id"], "shck": r["status"], "owner": None, "note": ""} for r in ordered[:size]]


def read_audit(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CaseError(f"cannot read audit file {path.name}: {exc}") from exc
    rows = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise CaseError(f"{path.name}:{number}: {exc}") from exc
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise CaseError(f"{path.name}:{number}: an audit line needs an id")
        if row.get("owner") is not None and row["owner"] not in OWNER_STATUSES:
            raise CaseError(
                f"{path.name}:{number}: owner must be one of {', '.join(OWNER_STATUSES)}"
            )
        rows.append(row)
    return rows


def audit_report(rows: list[dict], audits: list[dict]) -> dict:
    """Agreement of shck's status with the owner's, and the share of valid extracted facts."""
    status = {r["id"]: r["status"] for r in rows}
    known = [a for a in audits if a["id"] in status and a.get("owner") is not None]
    valid = [a for a in known if a["owner"] != "invalid-fact"]
    agree = sum(status[a["id"]] == a["owner"] for a in valid)
    return {
        "audited": len(known),
        "unknown_ids": sum(a["id"] not in status for a in audits),
        "agreement": _share(agree, len(valid)),
        "extractor_precision": _share(len(valid), len(known)),
    }


def _share(hits: int, total: int) -> dict:
    low, high = wilson(hits, total)
    return {"hits": hits, "n": total, "wilson": [round(low, 4), round(high, 4)]}


def render_text(run: dict) -> str:
    summary = run["summary"]
    lines = [
        f"{summary['n']} facts: present {summary['present']}, weak {summary['weak']}, "
        f"absent {summary['absent']} (finder {run['finder']['shck']}, "
        f"config {run['finder']['config_hash']})"
    ]
    for row in run["facts"]:
        best = row["candidates"][0]["path"] if row["candidates"] else "-"
        lines.append(f"{row['status']:7} {row['coverage']:.2f} {row['id']}  {best}")
    if "audit" in run:
        audit = run["audit"]
        lines.append(
            f"audit: {audit['audited']} audited, agreement {audit['agreement']['hits']} of "
            f"{audit['agreement']['n']}, valid facts {audit['extractor_precision']['hits']} of "
            f"{audit['extractor_precision']['n']}"
        )
    for row in run.get("audit_sample", []):
        lines.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(lines) + "\n"
