# `shck eval`

`shck eval` runs a file of cases through `shck find` and reports where the expected record lands. It measures retrieval; it never changes the finder, and it never writes a file: redirect the JSON to `<eval dir>/runs/<date>-<label>.json` yourself.

```sh
shck eval [--set ledger|probes|FILE] [--snapshot COMMIT --git-dir DIR | --live] [--k 3]
          [--baseline RUN.json] [--abstain-below X] [--gate] [--format json|text]
shck eval compare A.json B.json [--k 3] [--format json|text]
```

The default format is `json` (a run is data); `eval compare` prints text unless `--format json` is given.

## Case files

JSONL, one object per line, in the folder `[eval] dir` (relative to the profile) as `ledger.jsonl` and `probes.jsonl`, or any file given to `--set`.

**Ledger (tier A)**: one real failure per line.

```json
{"id": "L-0007", "date": "2026-10-21", "snapshot": "abc1234", "query": "...",
 "expect": "notes/x.md", "must_contain": "approve", "first_failing_stage": "retrieve",
 "cluster": "topic-id", "must_pass": true, "labeller": "owner", "ambiguous": false,
 "tags": [], "note": ""}
```

- `expect` is a record path, or `"none"` when no correct record existed at the snapshot (a capture or write failure); a `none` case runs as an abstention item.
- `must_contain` is a string the expected file must contain, so the gold is a path plus a string check and no record has to be created for the test. A case whose expected file is missing or lacks the string is `invalid` and is left out of every metric.
- `first_failing_stage` is one of `capture write trigger retrieve use`. It is data: eval never infers it.
- `must_pass` is set by a person; `--gate` reads it.
- Ledger lines are append-only; change one only by adding a `note`.

**Probes (tier B)**:

```json
{"id": "P-0042", "query": "...", "expect": "notes/x.md", "source_path": "notes/x.md",
 "writer": "model-name", "audited": false, "labels": {}}
{"id": "P-A007", "query": "...", "expect": "none", "abstain": true}
```

`labels` maps result paths to `relevant`, `irrelevant` or `on-topic-wrong`, and exists only for the owner audit. `probes.freeze.json` beside `probes.jsonl` may hold `{"sha256": ..., "count": ..., "audit_rate": ..., "audited": [...]}`; a run reports whether the file still matches. A changed hash is a new set version.

## Which tree

- `--live` searches the live tree for every case.
- `--snapshot COMMIT` searches that commit of the history repository for every case.
- Otherwise each case uses its own `snapshot` when it has one, else the live tree.

A snapshot needs `--git-dir` or `[eval] git_dir`. The commit is read with `git archive` into a temporary folder, not `git worktree add`, so the history repository is never written. One index is built per distinct tree and cached by tree hash, so a second run of the same snapshots reads no files.

## Metrics

Per set version, tree, and finder version (shck version and profile hash):

- **Hit@k** (`[eval] k`, default 1, 3, 10) and **MRR** (rank cap `[eval] rank_cap`, default 50; beyond it counts 0), with Wilson 95% intervals, over valid cases that have a path.
- **Irrelevant in top k**: only over (case, path) pairs that carry a label; otherwise `null` with `reason: "no labels"`. Never computed from heuristics.
- **Abstention** on `none` cases: the share whose top score is below `--abstain-below` (or `[eval] abstain_below`). Until a threshold is set, the run lists the top scores so it can be chosen from data.
- **Lexical overlap guard**: for each case with a `source_path`, the share of query tokens found in the source's title, alias and name tokens. Hit@k is reported for three buckets (`0`, `under_0.34`, `0.34_or_more`), so vocabulary-shifted claims are checked, not assumed.
- **Per case**: rank, top path and score. With `--baseline`, `newly_lost` and `newly_won` list case ids at `--k`.

## `compare`

Pairs two runs on case id. Only probe cases are tested: `b` counts cases where A hit and B missed, `c` the reverse, and the p-value is the exact two-sided McNemar test over `n = b + c` (binomial, p 0.5). Below `0.05` the verdict names the better run; otherwise it says "no detectable change". A split of 15 to 5 gives `p = 0.041`; 33 to 17 gives `p = 0.033`; with 50 discordant pairs 33 to 17 is the smallest split that clears 0.05. Ledger cases are never used for the test, as they are too few and too clustered; their per-case losses are listed.

## `--gate`

Exit `1` when

- a ledger case with `must_pass: true` ranks its expected record outside the top 3 on its own snapshot, or its gold is invalid (a case that cannot be checked protects nothing), or
- the median number of labelled irrelevant paths in the top 3 rose against `--baseline`. Without labels in the run or the baseline this clause is skipped and the run says so.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Run finished; with `--gate`, the gate passed. |
| `1` | `--gate` failed. |
| `2` | Usage or profile error: unknown key, missing `[eval] dir`, snapshot without `--git-dir`, unusable baseline. |
| `3` | A case file is unreadable or invalid, a snapshot commit is missing, or the root cannot be read. |
