# shouldercheck

**Look before you act.**

shouldercheck checks that a coding agent read the records it relies on before it publishes or delegates work. The command is `shck`.

> Status: experimental. Nothing below is implemented yet. This README describes the planned v0.1 behavior. There is no release yet.

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
shck check   # judge one action against the session evidence
shck find    # find earlier records about a topic
shck links   # check and update links between notes
```

## Requirements

- Python 3.11 or later. No runtime dependencies.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
