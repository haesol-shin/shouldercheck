"""Built-in values of the `[find]` profile keys. A profile overrides each of them.

Nothing here names a folder of a particular record base: the defaults assume only Markdown files
and English relation words.
"""

MARKER = "<!-- shck:index generated, do not edit -->"

# Bump when the tokenizer or the stored fields change: a cache from an older version is rebuilt.
TOKENIZER_VERSION = 1
SCHEMA_VERSION = 1

WEIGHTS = {"aliases": 4.0, "title": 3.0, "tags": 3.0, "summary": 2.0, "name": 2.0, "body": 1.0}
K1 = 1.2
B = 0.75
COVERAGE_POWER = 2.0
SUPERSEDED_FACTOR = 0.6
SUPERSEDED_STATUS = ("superseded",)
RELATIONS = {
    "follows": ("follows",),
    "basis": ("basis",),
    "superseded_by": ("superseded_by",),
    "supersedes": ("supersedes",),
    "related": ("related",),
}
NEIGHBORS = 8
SNIPPET_CHARS = 160
TIER_MAX_HITS = 3
DEFAULT_RANK = 1

LOG_TOP = 20
LOG_MAX_LINE_BYTES = 4096
LOG_KEEP_DAYS = 90
LOG_MAX_BYTES_PER_DAY = 5_000_000
