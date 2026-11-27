from tests.records.conftest import check, rows

ON = '[checks]\nsize = "warn"\n'


def sizes(root, config):
    return [(s, p, t) for s, p, _, t in rows(check(root, config), "size")]


def test_size_is_opt_in(tree):
    assert check(tree({"a.md": "x" * 100_000})).findings == []


def test_characters_not_bytes_decide_the_document_limit(tree):
    def text(chars: str, count: int) -> str:
        return (chars * 99 + "\n") * (count // 100)

    root = tree({"ko.md": text("가", 1_000), "en.md": text("a", 1_500), "big.md": text("a", 3_000)})
    toml = "[size]\nwarn_chars = 1200\nhigh_chars = 2000\n[checks]\nsize = 'warn'\n"
    # 1,000 Hangul characters are 3,000 bytes but stay under the limit.
    assert sizes(root, toml) == [("warn", "big.md", "chars"), ("candidate", "en.md", "chars")]


def test_long_line_is_found_even_in_a_short_document(tree):
    root = tree({"a.md": "short\n" + "x" * 300 + "\nshort\n" + "y" * 250 + "\n"})
    report = check(root, "[size]\nmax_line_chars = 200\n" + ON)
    [finding] = report.findings
    assert (finding.severity, finding.line, finding.target) == ("warn", 2, "line-length")
    assert "line of 300 characters" in finding.message and "2 long" in finding.message


def test_map_budget_applies_to_maps_only(tree):
    root = tree({"index.md": "x" * 600, "other.md": "x" * 600})
    toml = '[size]\nmaps = ["index.md"]\nmap_budget_chars = 500\n' + ON
    assert sizes(root, toml) == [("candidate", "index.md", "map-budget")]


def test_exclude_skips_source_copies(tree):
    root = tree({"sources/paper.md": "x" * 600, "a.md": "x" * 600})
    toml = '[size]\nwarn_chars = 500\nhigh_chars = 5000\nexclude = ["sources/**"]\n' + ON
    assert sizes(root, toml) == [("candidate", "a.md", "chars")]


def test_oversized_file_findings_can_be_suppressed_per_path(tree):
    root = tree({"sources/p.md": "x" * 600})
    toml = '[[per-path-ignores]]\nglob = "sources/**"\nchecks = ["size"]\nreason = "copy"\n'
    toml = "[size]\nwarn_chars = 500\n" + ON + toml
    report = check(root, toml)
    assert report.findings == [] and report.suppressed["size"] == 1


def long_lines(root, config):
    return [(s, p, n, t) for s, p, n, t in rows(check(root, config), "size")]


def test_line_chars_names_every_long_line_with_its_length(tree):
    root = tree({"a.md": "short\n" + "x" * 460 + "\nshort\n" + "y" * 451 + "\n" + "z" * 450 + "\n"})
    report = check(root, "[size]\nline_chars = 450\n" + ON)
    assert [(f.severity, f.path, f.line, f.target) for f in report.findings] == [
        ("warn", "a.md", 2, "line-chars"),
        ("warn", "a.md", 4, "line-chars"),
    ]
    assert [f.message for f in report.findings] == [
        "line of 460 characters (over 450)",
        "line of 451 characters (over 450)",
    ]


def test_line_chars_counts_characters_and_follows_the_check_severity(tree):
    root = tree({"ko.md": "가" * 300 + "\n", "ok.md": "가" * 200 + "\n"})
    toml = "[size]\nline_chars = 250\n[checks]\nsize = 'error'\n"
    assert long_lines(root, toml) == [("error", "ko.md", 1, "line-chars")]


def test_line_chars_is_off_by_default_and_replaces_the_longest_line_row(tree):
    root = tree({"a.md": "x" * 300 + "\n"})
    assert check(root, "[size]\n" + ON).findings == []
    # Both limits crossed: one row per long line, not a second summary row for the same line.
    both = "[size]\nmax_line_chars = 200\nline_chars = 100\n" + ON
    assert long_lines(root, both) == [("warn", "a.md", 1, "line-chars")]
    assert long_lines(root, "[size]\nmax_line_chars = 200\n" + ON) == [
        ("warn", "a.md", 1, "line-length")
    ]


def test_line_chars_respects_exclude(tree):
    root = tree({"sources/p.md": "x" * 300 + "\n"})
    toml = '[size]\nline_chars = 100\nexclude = ["sources/**"]\n' + ON
    assert check(root, toml).findings == []
