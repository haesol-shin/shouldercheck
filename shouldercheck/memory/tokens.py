"""One tokenizer for documents and queries, and the mask for every printed string."""

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache

from shouldercheck.memory.defaults import SNIPPET_CHARS

# Hangul, Kana and Han runs become character bigrams; Latin and digit runs stay words.
TOKEN = re.compile(r"[가-힣぀-ヿ㐀-䶿一-鿿]+|[a-z0-9]+")
LATIN = re.compile(r"[a-z0-9]")

_L, _R = r"(?<![0-9A-Za-z])", r"(?![0-9A-Za-z])"
BUILTIN_MASKS = (
    re.compile(_L + r"(?:sk|pk|rk|ghp|gho|ghs|xox[abp])[-_][A-Za-z0-9_-]{16,}"),
    # Long mixed-case strings that contain a digit look like keys.
    re.compile(
        r"(?<![0-9A-Za-z/_-])(?=[A-Za-z0-9+_-]*[A-Z])(?=[A-Za-z0-9+_-]*[a-z])(?=[A-Za-z0-9+_-]*\d)"
        r"[A-Za-z0-9+_-]{32,}={0,2}"
    ),
    re.compile(_L + r"\d{4}([ -])\d{4}\1\d{4}\1\d{3,4}" + _R),
    re.compile(
        r"(?i)(?<![A-Za-z])(password|passwd|passcode|pin|token|secret|api[_ -]?key)\s*[:=]\s*\S+"
    ),
)
LONG_DIGITS = re.compile(r"\d(?:-?\d){9,}")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for chunk in unicodedata.normalize("NFC", text).lower().split():
        tokens += _chunk_tokens(chunk)
    return tokens


@lru_cache(maxsize=100_000)
def _chunk_tokens(chunk: str) -> tuple[str, ...]:
    """Tokens of one whitespace-free chunk; words repeat a lot, so a build reuses most of them."""
    tokens: list[str] = []
    runs = TOKEN.findall(chunk)
    for run in runs:
        if not LATIN.match(run[0]):
            if len(run) >= 2:
                tokens += [run[i : i + 2] for i in range(len(run) - 1)]
            elif len(runs) == 1:
                tokens.append(run)
        else:
            plural = len(run) > 3 and run.endswith("s") and not run.endswith("ss")
            tokens.append(run[:-1] if plural else run)
    return tuple(tokens)


def norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower().strip()


class Masker:
    """Built-in secret shapes plus the profile's `[find] mask` patterns."""

    def __init__(self, extra: Iterable[re.Pattern[str]] = ()) -> None:
        self.patterns = (*BUILTIN_MASKS, *extra)

    def mask(self, text: str) -> str:
        text = str(text)
        for pattern in self.patterns:
            text = pattern.sub("***", text)
        return LONG_DIGITS.sub(lambda m: "*" * len(m.group(0)), text)

    def clip(self, text: object, limit: int = SNIPPET_CHARS, keep_space: bool = False) -> str:
        """Mask the whole string first, then cut it, so a secret is never cut in half."""
        value = "" if text is None else str(text)
        if not keep_space:
            value = " ".join(value.split())
        value = self.mask(value)
        return value if len(value) <= limit else value[: limit - 1] + "…"
