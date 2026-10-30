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
