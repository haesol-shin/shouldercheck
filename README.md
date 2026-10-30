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

## Requirements

- Python 3.11 or later. No runtime dependencies.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
