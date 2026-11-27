# `shck pack`

`shck pack` prints the sections of a record base that a session must read, then one receipt that proves which text was printed. A caller can run it at the start of a session so that what to read is decided by a list in the profile, not by the model.

```sh
shck pack [SELECTOR...] [--json] [--root DIR] [--config FILE]
```

## Guarantees

- **Read-only.** It reads the named files and writes nothing.
- **No model, no network.** Standard library only.
- **Byte-identical.** The same files and selectors give the same output: stable order, no timestamps, so the output can sit in a cached prompt prefix.
- **Never truncates.** If the selected text is over `max_chars`, it prints nothing and exits `2`.
- **Text as written.** Unlike `shck find`, it does not mask anything. The receipt hashes what is printed.

## Selectors

A selector is `path` for a whole file, or `path#heading` for one section. Paths are relative to the profile root and may not leave it: a `..` path, an absolute path or a symlink that points outside is refused.

A section runs from the heading line to the line before the next heading of the same or a higher level, so its nested headings are part of it. A `#` line inside fenced code is not a heading. The last section runs to the end of the file. Front matter belongs to no section.

A selector matches a heading when the heading text equals it, or starts with it followed by a space or `(`. `#Plan` matches `## Plan`, `## Plan (draft)` and `## Plan v2`, not `## Planning`. Closing hashes (`## Plan ##`) are not part of the text.

Zero matches, or more than one, is an error that names the selector and the matching lines. Pick a longer selector to disambiguate.

## Profile

```toml
[resume]
selectors = ["notes/project.md#Now", "notes/decisions.md#Storage"]
max_chars = 50000
```

| Key | Default | Meaning |
|---|---|---|
| `selectors` | none | The list used when no selector is given on the command line. Selectors on the command line replace it. |
| `max_chars` | `50000` | Most characters, summed over all selectors, that may be printed. |

No selector on the command line and none in `[resume]` is an error.

## Output

Each selector is printed as a fenced block, in the order given. The fence is longer than any run of backticks inside the text, so the text cannot close it. One receipt block ends the output; each line is `sha256`, characters, selector:

````text
shck pack

[1] notes/project.md#Now
```md
## Now

the state
```

receipt
```text
<sha256>  <characters>  notes/project.md#Now
```
````

The text is read as UTF-8, with CRLF and CR read as LF and trailing blank lines dropped, so the receipt does not change with the line endings or with a final newline. Characters are counted, not bytes. `--json` prints the same data:

```json
{"total_chars": 17, "sections": [{"selector": "notes/project.md#Now", "chars": 17, "sha256": "<sha256>", "text": "## Now\n\nthe state"}]}
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Printed. |
| `2` | Usage, config or selector error: unknown `[resume]` key, no selectors, a missing file, no or several matching headings, a path outside the root, text that is not UTF-8, or the `max_chars` cap. |
