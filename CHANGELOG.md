# Changelog

All notable changes to shouldercheck are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Project skeleton: documentation, CI, and issue and pull request templates.
- `shck check`: read-only report of dead links in a Markdown record base, with a TOML profile, frozen paths, per-path and inline ignores that require a reason, and text or JSON output.
- `shck check` reports links to headings that do not exist (`dead-anchor`) and resolves `[[wiki]]` links by stem, title or path; two candidates are reported as ambiguous, never guessed.
- `shck check` lists orphan files or folders, treating catalog files as link sources only; `frozen_manifests` freeze files listed by a manifest (an unreadable one exits 3); `--baseline` mutes earlier findings and `--paths` limits the listing to edited files.
- `shck check` reports missing or unexpected front matter fields (`missing-field`, with a fallback to `key: value` lines near the top and a per-folder rule) and aliases claimed by two documents (`alias-dup`).
