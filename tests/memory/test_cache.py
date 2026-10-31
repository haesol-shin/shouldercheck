import json
import os
import sqlite3

from shouldercheck.cli import main
from shouldercheck.memory import store
from tests.memory.conftest import find, paths

FILES = {
    "a.md": "# Alpha\n\nlaunch plan, see [b](b.md) and [later](later.md)\n",
    "b.md": "---\naliases: [Beta]\n---\nbeta launch notes\n\nsuperseded_by: [a](a.md)\n",
    "c.md": "unrelated gamma\n",
}


def view(result):
    """Everything a caller sees except how the index was opened."""
    return json.dumps({**result.to_json(), "index": result.index.docs}, sort_keys=True)


def bump(path, text):
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_warm_equals_cold_equals_memory(tree):
    root = tree(FILES)
    cold = find(root, "launch")
    warm = find(root, "launch")
    memory = find(root, "launch", use_cache=False)
    assert (cold.index.state, warm.index.state, memory.index.state) == ("cold", "warm", "memory")
    assert view(cold) == view(warm) == view(memory)


def test_the_index_lives_outside_the_record_base(tree, cache_home):
    root = tree(FILES)
    before = sorted(p.name for p in root.iterdir())
    find(root, "launch")
    assert sorted(p.name for p in root.iterdir()) == before
    assert len(list(cache_home.rglob("find.sqlite"))) == 1


def test_one_edited_file_is_parsed_again_and_nothing_else(tree):
    root = tree(FILES)
    find(root, "launch")
    bump(root / "c.md", "now about launch\n")
    result = find(root, "launch")
    assert result.index.state == "incremental"
    assert "c.md" in paths(result)
    assert view(result) == view(find(root, "launch", use_cache=False))


def test_removed_and_added_files_update_results_and_links(tree):
    root = tree(FILES)
    first = find(root, "launch")
    assert first.hits[0]["path"] == "a.md"
    assert [o["broken"] for o in first.hits[0]["outgoing"]] == [False, True]
    (root / "later.md").write_text("added\n", encoding="utf-8")
    (root / "b.md").unlink()
    second = find(root, "launch")
    assert "b.md" not in paths(second)
    assert [o["broken"] for o in second.hits[0]["outgoing"]] == [True, False]
    assert view(second) == view(find(root, "launch", use_cache=False))


def test_a_changed_profile_rebuilds(tree):
    root = tree(FILES)
    find(root, "launch")
    result = find(root, "launch", "[find.weights]\ntitle = 9\n")
    assert result.index.state == "cold"
    assert find(root, "launch", "[find.weights]\ntitle = 9\n").index.state == "warm"


def test_a_changed_tokenizer_version_rebuilds(tree, monkeypatch):
    root = tree(FILES)
    find(root, "launch")
    monkeypatch.setattr(store.defaults, "TOKENIZER_VERSION", 99)
    assert find(root, "launch").index.state == "cold"


def test_a_locked_index_falls_back_to_memory(tree, cache_home, monkeypatch, capsys):
    root = tree(FILES)
    find(root, "launch")
    monkeypatch.setattr(store, "BUSY_TIMEOUT", 0.05)
    bump(root / "c.md", "changed launch\n")
    db = next(cache_home.rglob("find.sqlite"))
    blocker = sqlite3.connect(db, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        result = find(root, "launch")
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert result.index.state == "memory" and "c.md" in paths(result)
    assert "locked" in capsys.readouterr().err


def test_an_unusable_cache_location_falls_back_to_memory(tree, tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
    root = tree(FILES)
    result = find(root, "launch")
    assert result.index.state == "memory" and paths(result)
    assert "cannot open index" in capsys.readouterr().err


def test_a_corrupt_index_falls_back_to_memory(tree, cache_home, capsys):
    root = tree(FILES)
    find(root, "launch")
    db = next(cache_home.rglob("find.sqlite"))
    db.write_bytes(b"not a database" * 100)
    result = find(root, "launch")
    assert result.index.state == "memory" and paths(result)
    assert capsys.readouterr().err


def test_cache_dir_key_is_relative_to_the_profile(tree):
    root = tree(FILES)
    find(root, "launch", '[find]\ncache_dir = "cache-here"\n')
    assert (root / "cache-here" / "find.sqlite").is_file()


def test_no_cache_flag_writes_nothing(tree, cache_home, capsys):
    root = tree(FILES)
    assert main(["find", "launch", "--root", str(root), "--no-cache", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["index"]["state"] == "memory"
    assert not cache_home.exists()


def test_the_index_is_private(tree, cache_home):
    find(tree(FILES), "launch")
    db = next(cache_home.rglob("find.sqlite"))
    assert db.stat().st_mode & 0o777 == 0o600
    assert db.parent.stat().st_mode & 0o777 == 0o700
