# `shck check`

`shck check` reads a folder of Markdown notes (a record base) and lists candidates with paths: broken links, orphans, missing fields and oversized files. It is read-only. It never edits, moves or deletes, and it does not decide what to fix. A person or an agent reads the report and decides.

```sh
shck check [--root DIR] [--config FILE] [--only CHECK[,CHECK]] [--skip CHECK[,CHECK]]
           [--paths PATH...] [--format text|json] [--max N]
           [--fail-on candidate|warn|error|never] [--baseline FILE]
```

## Guarantees

- **Read-only.** Files under the root are opened for reading only.
- **No symlinks.** A symlinked file in scope is skipped and listed under `scan.skipped`; a symlinked folder is not entered.
- **No network, no model, no external process.** Standard library only.
- **Deterministic.** Findings are sorted by check, path, line and target; the same tree gives byte-identical output. `stale` is the one exception: it compares dates with today.
- **Bounded output.** Every printed string is clipped to 200 characters. The report lists paths and link targets, never body text.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | The run completed and no finding reached `--fail-on` (default `never`). |
| `1` | At least one finding at or above `--fail-on`. |
| `2` | Usage or config error: unknown key, bad glob, unknown check, unusable baseline. |
| `3` | Input error that makes the report untrustworthy: missing root, unreadable frozen manifest. A partial report is still printed, with `scan.error` set. |

Severities rank `candidate` < `warn` < `error`. A `candidate` needs judgment and never fails a run unless `--fail-on candidate` says so.

## Profile

One TOML file per record base. Discovery order:

1. `--config FILE`.
2. `shck.toml` or `.shck.toml` in `--root` (or the current folder), then in each parent folder; the first one found wins.
3. The built-in profile: `**/*.md` under the current folder, excluding `.*/**`, `node_modules/**` and `**/*sfconflict*`; links `markdown` and `wiki`; `dead-link`, `dead-anchor` and `alias-dup` on.

`--root`, `--only`, `--skip`, `--fail-on` and `--format` override the file. Unknown keys are errors (exit `2`), so a typo never silently disables a check. Paths in the file are relative to the file. See [examples/shck.toml](examples/shck.toml) for a complete profile.

### Keys

| Key | Default | Meaning |
|---|---|---|
| `version` | `1` | Profile version. |
| `root` | `"."` | Record base folder, relative to the profile. |
| `include` | `["**/*.md"]` | Files in scope. |
| `exclude` | see built-in profile | Files never read. Write the reason as a comment. |
| `frozen` | `[]` | Files read as link sources whose own findings are only counted. |
| `frozen_manifests` | `[]` | File names (such as `hashes.json`, `*.sha256`) that list files by relative path; listed files are frozen. A manifest that cannot be read freezes its folder and ends the run with exit `3`. |
| `max_read_chars` | `2000000` | Larger files are skipped and listed, never truncated. |
| `links` | `["markdown", "wiki"]` | Link styles that count: `markdown`, `wiki`, `backtick`. |
| `fail_on` | `"never"` | Same as `--fail-on`. |
| `format` | `"text"` | Same as `--format`. |

Globs match relative POSIX paths. `*` stays inside one folder, `**` crosses folders, `**/` may match no folder.

`[links_opts]`: `wiki_resolve` (`stem`, `title`, `path`), `slug` (`github`, `mkdocs`, `obsidian`), `heading_ids`, `html_ids`, `backtick_dead`, `link_dirs` (booleans, default `false`).

`[orphans]`: `scope` (globs; the check is off while empty), `catalog` (link sources that do not count as inbound), `exempt` (globs) and `exempt_names` (file-name globs) skip files, `unit` (`file` or `folder`, default `file`), `folder_depth` (default `3`), `grace_days` (hide files younger than this many days by modification time; default `0`, off).

`[[fields.rules]]`: `match` (globs) or `folder_any = { in = [...], when_present = [...] }`, `require` (keys, at least one), `values` (allowed values per key), `body_lines` (default `false`), `body_lines_max` (default `12`).

`[size]`: `warn_chars` (default `30000`), `high_chars` (`50000`), `max_line_chars` (`2000`), `map_budget_chars` (`24000`), `maps` and `exclude` (globs).

`[stale]`: `match` (globs), `days` (default `14`), `field` (default `updated`).

`[checks]` sets the severity of a check's main findings (`error`, `warn`, `candidate`) or turns it `off`. On without input: `dead-link`, `dead-anchor`, `alias-dup`. `orphan` and `missing-field` are on but find nothing without `[orphans] scope` or `[[fields.rules]]`. `size`, `dup-content` and `stale` are opt-in.

## Checks

| Check | Severity | Rule |
|---|---|---|
| `dead-link` | `error`; `candidate` for label-like targets | An inline link, `[[wiki]]` link or (with `backtick_dead`) backtick path whose target does not exist. A target is cut at `#`, percent-decoded and resolved from the file's own folder, with no fallback to the root. External schemes, drive paths and targets starting with `/` or `~` are skipped. A target with no `/`, no extension, or with spaces outside `<...>` is label-like: a parenthetical remark that parsed as a link. A wiki name that matches two files is a `candidate`, never guessed. The hint says `moved? <path>` for a unique file of the same name and `renamed? <path>` for a unique dated or versioned one. |
| `dead-anchor` | `error` | A link with `#fragment` to a Markdown file in scope that has no such heading, under the `slug` rule. Block ids (`#^id`) are never flagged. |
| `orphan` | `warn`; `candidate` when only a catalog links it | A file, or with `unit = "folder"` a folder (the first `folder_depth` folders of the path), with no inbound link from another file. Links from `catalog` files do not count as inbound. Frozen files count as link sources. Off until `[orphans] scope` is set. |
| `missing-field` | `warn` | `[[fields.rules]]`: `match` globs need keys in each file; `folder_any` needs one file per folder with the key, only in folders holding a `when_present` file. Keys come from front matter, then (`body_lines = true`) from `key: value` lines in the first `body_lines_max` lines. A value is reduced to the text before the first space, `(` or `·` before it is compared with `values`. |
| `alias-dup` | `error`; `candidate` for a title or file-name clash | The same front matter alias on two documents, after case folding and removal of spaces, `-`, `.`, `_` and `·`. Frozen files own no alias. |
| `size` | `warn`; `candidate` | Characters (not bytes or words) over `warn_chars` (`candidate`) or `high_chars`; a line over `max_line_chars`; a `maps` file over `map_budget_chars` (`candidate`). `exclude` skips verbatim copies. |
| `dup-content` | as set in `[checks]` | Files over 200 bytes with identical bytes. The survivor is a human choice. |
| `stale` | as set in `[checks]` | Files matching `[stale] match` whose date in `field` (default `updated`) is older than `days`. |

## Exceptions

An exception should carry a reason, as in a linter.

```toml
[[per-path-ignores]]
glob = "fixtures/**"
checks = ["dead-link"]
reason = "fixture copies keep their original links"
```

```md
<!-- shck: ignore dead-link reason="target is generated later" -->
```

The inline comment skips the named check (several may be listed, comma separated) on its own line and the next line. A comment inside code is not a directive. An exception without `reason` still applies but is reported as a `warn` finding, `ignore-without-reason`. The report counts suppressed findings per check.

## Output

Text starts with a summary per check and severity, then lists rows per check (`--max` rows each, default 20). JSON is never truncated:

```json
{
  "schema_version": 1,
  "root": "<root>",
  "config": "shck.toml",
  "scan": {"files": 120, "frozen": 6, "skipped": []},
  "summary": {
    "error": 2, "warn": 1, "candidate": 3, "suppressed": 1,
    "by_check": {"dead-link": {"error": 2, "candidate": 3, "frozen": 4, "frozen_files": 2}}
  },
  "findings": [
    {"check": "dead-link", "severity": "error", "path": "notes/a.md", "line": 50,
     "target": "../guides/core.md", "message": "target not found",
     "hint": "moved? archive/core.md",
     "fingerprint": "dead-link|notes/a.md|../guides/core.md"}
  ]
}
```

Fields only grow. Removing or renaming one bumps `schema_version`. A fingerprint is `check|path|target` without the line number, so a baseline survives edits above a finding.

- `--paths FILE...` lists findings only for those files or folders, while links and orphans are still computed from the whole scope. This is the "check what I just edited" call.
- `--baseline report.json` mutes findings whose fingerprint is in an earlier JSON report and counts them as suppressed. shck never writes a baseline; redirect stdout.

## How agents call it

The core never imports an agent harness. A harness calls the command and reads the report.

- **Scheduled report.** Run `shck check --format json` from a scheduled agent job, read `summary`, and report the counts and the first rows per severity. Keep the previous run as `--baseline` to say only what is new. Scheduling belongs to the job, not to shck.
- **After edits.** A coding agent that edited the record base runs `shck check --paths <edited files> --format json --fail-on error`. A non-zero exit means the edit introduced a broken link or alias.
- **Both** treat the report as input to a decision. Neither applies fixes automatically; `hint` fields are suggestions.

## Out of scope

Editing or auto-fixing, external URL checking, semantic duplicates, reference-style and HTML links, notifications, non-Markdown files, and a superseded-without-successor check. Search and ranking are [`shck find`](find.md); the generated map is [`shck index`](index.md).
