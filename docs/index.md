# `shck index`

`shck index` generates a capped root map of a record base and, for a section that does not fit, a fuller `index.md` inside that section's folder. Agents read the short map first and follow a link to the overflow index only when they need it.

```sh
shck index [--check] [--diff] [--adopt] [--format text|json] [--root DIR] [--config FILE]
```

Without options it writes the generated files that differ. It never edits a hand-written file.

## Guarantees

- **Only generated files.** Every generated file starts with the line `<!-- shck:index generated, do not edit -->`. shck writes a path only when the file is absent or already starts with that line. A hand-written file at a generated path stops the run with exit `3` before anything is written.
- **Deterministic.** Entries are sorted, lines end in LF, there are no timestamps, and a file is written (through a temporary file and `os.replace`) only when its bytes differ. `mtime-desc` depends on file times, which differ across clones; use `name-desc` for dated file names where a clone must give the same map.
- **Never skipped by accident.** If the map is over `[size] map_budget_chars`, allowances shrink one entry at a time from the section with the largest allowance (ties in profile order), so no section disappears.
- **Map path.** `[index] map` may name a file in a subfolder. Every link in a generated file is relative to that file, so `maps/index.md` links to `../notes/a.md`.
- **Stale section indexes are kept, not deleted.** A generated `index.md` under a section root that the run no longer produces (for example after the section dropped below the cap) is overwritten with a marked one-line pointer to the nearest remaining index. `--check` exits `1` while such a file still holds the old listing.
- `shck find` skips generated files, and generated files are not listed as entries.

## Options and exit codes

| Option | Meaning |
|---|---|
| `--check` | Write nothing. Exit `1` when any generated file is absent or stale. Use it after edits and in CI. |
| `--diff` | Print the unified diff of every file that would change. |
| `--adopt` | Take over the existing unmarked file at the map path, once. Run it by hand at cut-over; routine callers never pass it. Section indexes are never adopted. |
| `--format json` | One JSON report (`schema_version` 1): `files` (path, status `new`/`stale`/`current`/`conflict`, chars), `written`, `map` (chars, budget), `shrunk`, `blocked`, `notes`. |

| Code | Meaning |
|---|---|
| `0` | Done, or with `--check` nothing is stale. |
| `1` | `--check` found a stale or absent generated file. |
| `2` | Usage or profile error, including a profile with no `[[index.sections]]`. |
| `3` | A hand-written file stands at a generated path (nothing was written), or the root cannot be read. |

## Profile

```toml
[index]
map = "index.md"
title = "Notes"
header = ["Locations only; no facts."]   # fixed lines under the title
top_title = "Top"
top_files = ["README.md", "profile.md"]  # listed first, when present
exclude = []                             # extra globs left out of the map

[[index.sections]]
id = "projects"
title = "Projects"
root = "projects"
mode = "tree"        # tree | recent | count
cap = 50             # defaults: tree 200, recent 20
order = "path"       # path | name-desc | mtime-desc (mtime-desc only for recent)
index = "folder"     # folder: write <root>/index.md on overflow | none
note = "one file per effort"   # optional italic line
```

Entries are the Markdown files under a section's root, minus the profile's `exclude` globs and `[index] exclude`. The deepest root owns a file, so `people` under `areas` is a section of its own. Unknown or repeated ids, repeated roots, bad modes and roots that leave the base are profile errors.

## Output

The root map has the marker, the title, the header, the top files, then one block per section: a heading with the root, the entries up to the allowance, and, when entries remain, `_N more, see [<root>/index.md](<...>)_` (or `_N more_` without a section index).

- `tree` groups entries by folder.
- `recent` lists the first entries in `order` and has no overflow file.
- `count` prints the number of files per immediate subfolder.

An entry is `[title](<path>)`; the title is the front matter `title`, else the first `# ` heading, cut to 80 characters, else the file name.

A section index lists all entries of its section grouped by folder; each folder is one group, with its direct files first. A generated section index that already exists is kept current even when the section no longer overflows. If one is over the budget, each immediate subfolder gets its own index and the parent lists them with counts. The depth is limited to three levels; below that a count line replaces the listing and the report carries a `size` note.

## With `shck check`

Generated indexes link to many files. Declare them as maps and as link sources in the profile:

```toml
[size]
maps = ["**/index.md"]

[orphans]
catalog = ["**/index.md"]
```
