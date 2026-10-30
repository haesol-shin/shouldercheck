# shouldercheck

**Look before you act.**

shouldercheck checks that a coding agent read the records it relies on before it publishes or delegates work. The command is `shck`.

> Status: experimental. Only `shck check` (see Commands (available)) is implemented; the rest describes planned behavior. There is no release yet.

## What it is not

- It does not call a model. Every check is plain code.
- It does not judge whether the work is good. It checks only that the required records were read and the required review exists.
- It does not modify the agent harness. Adapters use only each harness's public plugin or extension API.

## The problem

An agent starts a new session, or its context is compressed. It no longer remembers what was already decided, found, or reviewed. It then pushes a change without the review it was told to get, or hands work to another agent without the earlier findings. The rules were written down, but nothing checked them at the moment of the action.

## How it will work (planned)

- **Two layers.**
  - Inside a repository: publishing actions (`git push`, `gh pr create`, `gh pr merge`, comments) need a passing review for the exact commit or text.
  - Across repositories: a delegation brief lists the earlier records it builds on, and each listed record must have been opened in the same session. A search with no result also counts when the brief names that search.
- **Evidence.** Adapters record what the session actually opened. A path in a search result is not a read.
- **Warn first.** The first mode only warns and writes one JSON line per warning. Blocking is a separate setting.
- **Harness neutral.** The judging core takes an action, a target, and an evidence file. Thin adapters for Hermes Agent and omp collect the evidence and call the core.
- **Find and link.** `shck find` and `shck links` search a Markdown knowledge base and keep links between notes up to date.

## Commands (planned)

```sh
shck find    # find earlier records about a topic
shck links   # check and update links between notes
```

## Commands (available)

```sh
shck check   # report broken structure in a Markdown record base (read-only)
```

`shck check` reads a folder of Markdown notes and lists candidates with paths. It never edits, moves or deletes anything, and it does not decide what to fix. Exit code `0` means the run completed, `1` means a finding reached `--fail-on` (default `never`), `2` a usage or config error, `3` an input error.

```sh
shck check --root notes/ --format json --fail-on error
```

Without a profile it checks dead links in `**/*.md`. A `shck.toml` or `.shck.toml` at the root of the record base narrows the scope and sets exceptions:

```toml
version = 1
include = ["notes/**/*.md"]
exclude = ["notes/drafts/**"]
frozen = ["notes/snapshots/**"]   # read, but their findings are only counted

[[per-path-ignores]]
glob = "notes/fixtures/**"
checks = ["dead-link"]
reason = "fixture copies keep their original links"
```

An inline exception skips one check for its own line and the next line:

```md
<!-- shck: ignore dead-link reason="target is generated later" -->
```

An exception without a `reason` still applies, but is reported as an `ignore-without-reason` warning. The report counts suppressed findings per check.

Link styles and anchors are set in the profile. `links` picks which styles count (`markdown`, `wiki`, `backtick`; default `markdown` and `wiki`). Under `[links_opts]`, `wiki_resolve` is `stem`, `title` or `path`, and `slug` is `github`, `mkdocs` or `obsidian`; `heading_ids`, `html_ids`, `backtick_dead` and `link_dirs` are off by default. A `[[wiki]]` name that matches two files is a `candidate`, never resolved by guess.

The `orphan` check is on only when `[orphans] scope` is set. A file with no inbound link from another file is a `warn`; a file linked only from a `catalog` file (a generated index) is a `candidate`. With `unit = "folder"` the unit is the first `folder_depth` folders of the path, which suits job folders that are meant to stay unlinked; a file with fewer folders is its own unit. `exempt` and `exempt_names` skip entry files and inputs. `grace_days` hides files younger than that many days by modification time, and is off by default.

```toml
frozen_manifests = ["hashes.json", "*.sha256"]   # files these list are frozen

[orphans]
scope = ["notes/**"]
catalog = ["index.md"]
exempt_names = ["intent.md"]
unit = "folder"
folder_depth = 3
```

A manifest that cannot be read freezes its whole folder and ends the run with exit code `3`. `--paths FILE...` lists findings only for those files while the link graph still covers the whole scope. `--baseline report.json` mutes findings whose fingerprint is in an earlier JSON report (`shck check --format json > report.json`); shck itself never writes it.

`[[fields.rules]]` entries make the `missing-field` check. A `match` rule requires keys in every matching file. With `body_lines = true` a `key: value` line in the first `body_lines_max` lines counts too, and `status: active · updated: 2026-10-20` reads as `active`. A `folder_any` rule asks that at least one file in each matching folder has the key, only in folders that hold a file matching `when_present`.

```toml
[[fields.rules]]
match = ["projects/*.md"]
require = ["status"]
values = { status = ["active", "hold", "done"] }
body_lines = true

[[fields.rules]]
folder_any = { in = ["jobs/*"], when_present = ["result*.md"] }
require = ["owner"]
```

`alias-dup` reads `aliases` from front matter. The same alias on two documents is an `error`; an alias equal to another document's title or file name is a `candidate`. Frozen files own no alias.

`dup-content`, `stale` and `size` are off until `[checks]` turns them on. `size` counts characters, not bytes or words, and reports a document over `warn_chars` as a `candidate`, one over `high_chars` as a `warn`, a line over `max_line_chars`, and a `maps` file over `map_budget_chars`; `exclude` skips verbatim source copies. `dup-content` lists files with identical bytes (over 200 bytes) and leaves the survivor to a person. `stale` reads the `updated:` date of files matching `[stale] match` and lists those older than `days`.

```toml
[checks]
size = "warn"
dup-content = "candidate"
stale = "candidate"

[size]
warn_chars = 30000
high_chars = 50000
max_line_chars = 2000
maps = ["index.md"]
exclude = ["**/sources/**"]

[stale]
match = ["projects/*.md"]
days = 14
```

## Requirements

- Python 3.11 or later. No runtime dependencies.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
