# `shck find`

`shck find` ranks the records of a Markdown record base against a query and lists each hit with the records it links to. It reads files and writes nothing into the record base.

```sh
shck find QUERY... [--limit 10] [--format text|json] [--scope records|transcript|all]
                   [--neighbors N] [--caller NAME] [--session ID] [--no-log] [--no-cache] [--root DIR] [--config FILE]
```

## Guarantees

- **Read-only on the record base.** It writes only the derived index (see [Speed and freshness](#speed-and-freshness)) and the query log (see [Query log](#query-log)), both outside the base.
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

From the index, without reading files: outgoing links with the relation word that stands before the link (`word:` or `**word**:`), incoming links from other records, and other documents that share an alias (never merged). At most `--neighbors` (default 8) per direction; titles are cut to 160 characters.

A document is superseded when its front matter `status` is in `superseded_status`, when it has an outgoing link after a `superseded_by` word, or when another record links to it after a `supersedes` word.

## Transcript tier

Chat logs and similar transcripts can be searched at a low rank. A tier is a set of files outside the record scope (they are not in the top-level `include`, so `shck check` never reads them):

```toml
[[find.tiers]]
name = "transcript"
include = ["chat/*.md"]
unit = "entry"                      # file, or entry: split at lines matching entry_pattern
entry_pattern = '^### \d{2}:\d{2} · m(\d+)$'   # group 1 names the entry
anchor_prefix = "m"                 # an entry's path is chat/2026-01-01.md#m123
max_hits = 3
```

- **Separate statistics.** A tier has its own term counts, so scores of tiers are never mixed.
- **Low rank is structural.** Tier hits never stand above a record. They come in the `transcript` array after the records, with ranks that continue, and under their own heading in text. At most `max_hits` (default 3) per tier.
- **Prefix.** Each entry is indexed with its file title and date.
- A file that matches both the record scope and a tier stays a record. `--scope records|transcript|all` (default `all`) picks the arrays.

## Output

Text: one block per hit. JSON (`schema_version` 1; fields only grow):

```json
{"schema_version": 1, "query": "...", "caller": "omp",
 "index": {"state": "warm", "docs": 120, "ms": 41},
 "hits": [{"rank": 1, "tier": "records", "path": "...", "score": 12.34,
           "matched": ["alias", "title", "body"], "title": "...", "summary": "...",
           "snippet": "...", "status": null, "superseded": false, "replaced_by": [],
           "same_alias_as": [], "aliases": [], "outgoing": [], "incoming": [],
           "outgoing_total": 0, "incoming_total": 0}],
 "transcript": []}
```

`matched` and `snippet` are computed for the returned hits only, by reading those files. The snippet is the best-matching line, masked and cut to 160 characters.

`caller` is the value logged for this call (see below).

Exit codes: `0` (with hits or none), `2` config error, `3` the record base cannot be read.

## Query log

Every call appends one line to `YYYY-MM-DD.jsonl` (UTC day) in `$XDG_STATE_HOME/shck/<root hash>/queries/`, outside the record base. It separates "the agent did not search" from "the agent searched and missed".

```json
{"v": 1, "ts": "2026-10-31T11:20:05+00:00", "caller": "omp", "session": null,
 "query": "...", "scope": "all", "paths": null, "limit": 10,
 "ranked": [["notes/launch-plan.md", 2.35, "records"]], "top_score": 2.35,
 "n_hits": 10, "index": "warm", "ms": 214, "shck": "0.0.0", "config_hash": "ab12cd34",
 "snapshot": null}
```

- **Caller.** `--caller` wins, then `$SHCK_CALLER`, else `unknown`. `--session` then `$SHCK_SESSION`. shck only defines the contract; the agent's rules or environment set the value, for example `shck find --caller omp ...`. A report counts `unknown` as a visible gap.
- **Privacy.** The query and paths are masked with the same mask as the output. Snippets, neighbours and record text are never logged. The folder is mode `0700`, files `0600`.
- **Size.** `ranked` keeps the top `log_top` (20) entries. A line over `max_line_bytes` (4096) drops entries from the end of `ranked`, so one `O_APPEND` write holds one line and concurrent callers do not interleave. After `max_bytes_per_day` (5 MB) the day gets one `{"truncated":true}` line and nothing more.
- **Retention.** Day files older than `keep_days` (90) are gzip-compressed in place (`YYYY-MM-DD.jsonl.gz`) on the next write, after the compressed copy reads back equal. Nothing is deleted; a day written again after compression gets a second gzip member.
- **Limits.** A failure to write prints one line to stderr and never fails `find`. Only `shck find` calls appear: a `cat` or `grep` of a record does not. `--no-log` skips the line; library callers (eval, gaps) never log.

## Profile

All keys are optional and live in the `[find]` table of `shck.toml`; unknown keys are errors.

| Key | Default | Meaning |
|---|---|---|
| `weights` | see above | Table of field weights. |
| `k1`, `b`, `coverage_power`, `superseded_factor` | 1.2, 0.75, 2, 0.6 | Ranking constants. |
| `superseded_status` | `["superseded"]` | Front matter `status` values that mark a document superseded. |
| `exact_name_first` | `true` | The exact-name order above. |
| `neighbors` | 8 | Default for `--neighbors`. |
| `tiers` | none | `[[find.tiers]]` tables as above. |
| `mask` | `[]` | Regular expressions masked in every printed string, besides the built-in secret shapes. |
| `log` | see Query log | `[find.log]`: `dir`, `keep_days`, `max_bytes_per_day`, `log_top`, `max_line_bytes`. |
| `cache_dir` | `$XDG_CACHE_HOME/shck/<root hash>/` | Folder of the derived index. |

`[find.relations]` maps a relation name to the words that stand before a link: `follows`, `basis`, `superseded_by`, `supersedes`, `related` (defaults are the English names). `[[find.priority]]` entries (`glob`, `rank`) order exact-name hits; the first matching glob wins.

## Speed and freshness

The index is a derived SQLite file (term counts, links, names) outside the record base, in `cache_dir`. Each call walks the scope, compares size and modification time of each file, and parses only changed files; a changed profile, tokenizer or schema rebuilds it. `--no-cache` builds it in memory. Delete the folder at any time; nothing else depends on it. If the index is locked or cannot be opened, the call builds in memory and prints one line to stderr.
