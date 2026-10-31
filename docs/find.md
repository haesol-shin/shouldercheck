# `shck find`

`shck find` ranks the records of a Markdown record base against a query and lists each hit with the records it links to. It reads files and writes nothing into the record base.

```sh
shck find QUERY... [--limit 10] [--format text|json]
                   [--neighbors N] [--root DIR] [--config FILE]
```

## Guarantees

- **Read-only.** It writes nothing.
- **No model, no network.** Standard library only.
- **Deterministic.** The same tree and query give the same order; ties break on the path.
- **Bounded, masked output.** Every printed string is masked, then cut to 160 characters.

## Documents and fields

A document is a Markdown file in scope (`include` and `exclude`, shared with `shck check`). Files whose first line is the marker of a generated index are skipped, so maps never pollute the ranking.

| Key | Source | Default weight |
|---|---|---|
| `aliases` | front matter `aliases` | 4 |
| `title` | front matter `title`, else the first `# ` heading in the first 30 lines, else the file name | 3 |
| `tags` | front matter `tags` | 3 |
| `summary` | front matter `summary` | 2 |
| `name` | file name, with `-` and `_` as spaces | 2 |
| `body` | everything after the front matter | 1 |

Each key's term count is multiplied by its weight and summed per term. A hit's own `summary` is the front matter value, else the first quote line, else the first prose line.

## Tokens

Text is NFC-normalised and lower-cased. Hangul, Han and Kana runs become character bigrams (a lone one-character word keeps its unigram), so `논문을` matches `논문`. Latin and digit runs are words; a trailing plural `s` is dropped on words over 3 letters. Documents and queries use the same tokenizer.

## Score and order

BM25 (`k1` 1.2, `b` 0.75) over the weighted term counts, times `(matched terms / query terms) ^ coverage_power` (default 2). A document with score 0 never appears. A superseded document is multiplied by `superseded_factor` (0.6) and tagged, never dropped.

Order:

1. Exact names (key `exact_name_first`, default on): a hit whose alias or title equals the query or one of its words comes first (tier 0); a hit whose file name alone matches comes next (tier 1). Inside a tier: not superseded first, then folder priority (`[[find.priority]]`, default rank 1), then score.
2. Everything else by score, then path.

## Neighbours

From the index: outgoing links with the relation word that stands before the link (`word:` or `**word**:`), incoming links from other records, and other documents that share an alias (never merged). At most `--neighbors` (default 8) per direction; titles are cut to 160 characters.

A document is superseded when its front matter `status` is in `superseded_status`, when it has an outgoing link after a `superseded_by` word, or when another record links to it after a `supersedes` word.

## Output

Text: one block per hit. JSON (`schema_version` 1; fields only grow):

```json
{"schema_version": 1, "query": "...",
 "index": {"state": "warm", "docs": 120, "ms": 41},
 "hits": [{"rank": 1, "tier": "records", "path": "...", "score": 12.34,
           "matched": ["alias", "title", "body"], "title": "...", "summary": "...",
           "snippet": "...", "status": null, "superseded": false, "replaced_by": [],
           "same_alias_as": [], "aliases": [], "outgoing": [], "incoming": [],
           "outgoing_total": 0, "incoming_total": 0}]}
```

`matched` and `snippet` are computed for the returned hits only, by reading those files. The snippet is the best-matching line, masked and cut to 160 characters.

Exit codes: `0` (with hits or none), `2` config error, `3` the record base cannot be read.

## Profile

All keys are optional and live in the `[find]` table of `shck.toml`; unknown keys are errors.

| Key | Default | Meaning |
|---|---|---|
| `weights` | see above | Table of field weights. |
| `k1`, `b`, `coverage_power`, `superseded_factor` | 1.2, 0.75, 2, 0.6 | Ranking constants. |
| `superseded_status` | `["superseded"]` | Front matter `status` values that mark a document superseded. |
| `exact_name_first` | `true` | The exact-name order above. |
| `neighbors` | 8 | Default for `--neighbors`. |
| `mask` | `[]` | Regular expressions masked in every printed string, besides the built-in secret shapes. |

`[find.relations]` maps a relation name to the words that stand before a link: `follows`, `basis`, `superseded_by`, `supersedes`, `related` (defaults are the English names). `[[find.priority]]` entries (`glob`, `rank`) order exact-name hits; the first matching glob wins.

## Speed

Each call parses every file in scope and builds the index in memory.
