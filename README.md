# shouldercheck

**Look before you act.**

shouldercheck checks that a coding agent read the records it relies on before it publishes or delegates work. The command is `shck`.

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
- **Links.** `shck links` keeps links between notes up to date.

## Commands (planned)

```sh
shck links   # check and update links between notes
```

## Commands (available)

```sh
shck check   # report broken structure in a Markdown record base (read-only)
shck find    # find earlier records about a topic, ranked, with linked neighbours
```

`shck check` reads a folder of Markdown notes and lists candidates with paths. It never edits, moves or deletes anything, and it does not decide what to fix. A TOML profile (`shck.toml` or `.shck.toml`) sets the scope, the checks and the exceptions; without one, a built-in profile applies.

```sh
shck check --root notes/ --format json --fail-on error
```

Profile keys, checks, exceptions, output, exit codes and how agents call it: [docs/check.md](docs/check.md).

The memory commands help an agent find a record before it acts:

- `shck find` ranks records by weighted fields, lists linked neighbours, can search transcripts at a low rank: [docs/find.md](docs/find.md).

## Requirements

- Python 3.11 or later. No runtime dependencies.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
