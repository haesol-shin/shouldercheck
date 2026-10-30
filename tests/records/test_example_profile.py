from pathlib import Path

from shouldercheck.records.config import load_config
from shouldercheck.records.report import run_check

EXAMPLE = Path(__file__).parents[2] / "docs" / "examples" / "shck.toml"


def test_documented_example_profile_loads_and_runs(tree):
    root = tree(
        {
            "projects/README.md": "# Projects\n",
            "projects/a.md": "status: active\n[x](gone.md)\n",
            "jobs/one/result.md": "no owner\n",
        }
    )
    report = run_check(load_config(EXAMPLE, root, root))
    found = {(f.check, f.path) for f in report.findings}
    assert found == {
        ("dead-link", "projects/a.md"),
        ("missing-field", "jobs/one/"),
        ("orphan", "jobs/one/"),
    }
    assert report.suppressed["missing-field"] == 1
    assert report.error is None
