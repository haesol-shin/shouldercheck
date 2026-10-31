import gzip
import json
import threading
from datetime import UTC, date, datetime

from shouldercheck.cli import main
from shouldercheck.memory import qlog
from shouldercheck.memory.find import run_find
from shouldercheck.memory.settings import find_settings
from tests.memory.conftest import find, load

FILES = {"a.md": "launch plan\n", "b.md": "launch notes\n", "c.md": "other\n"}
NOW = datetime(2026, 10, 31, 11, 20, 5, tzinfo=UTC)


def lines(state_home):
    files = sorted(state_home.rglob("*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text("utf-8").splitlines()]


def run(root, *args):
    return main(["find", *args, "--root", str(root)])


def test_one_line_per_call_with_caller_and_no_snippets(tree, state_home, capsys):
    root = tree(FILES)
    assert run(root, "launch", "--caller", "omp", "--session", "s1", "--format", "json") == 0
    assert run(root, "launch", "--limit", "1") == 0
    first, second = lines(state_home)
    assert first["caller"] == "omp" and first["session"] == "s1"
    assert second["caller"] == "unknown" and second["session"] is None
    assert first["query"] == "launch" and first["v"] == 1
    assert {row[0] for row in first["ranked"]} == {"a.md", "b.md"}
    assert first["n_hits"] == 2 and second["n_hits"] == 1 and second["limit"] == 1
    assert first["top_score"] == first["ranked"][0][1]
    assert "snippet" not in json.dumps(first) and "outgoing" not in json.dumps(first)
    assert json.loads(capsys.readouterr().out.split("\n1. ")[0])["caller"] == "omp"


def test_caller_comes_from_the_environment_after_the_flag(tree, state_home, monkeypatch):
    root = tree(FILES)
    monkeypatch.setenv("SHCK_CALLER", "hermes")
    monkeypatch.setenv("SHCK_SESSION", "env-session")
    run(root, "launch")
    run(root, "launch", "--caller", "flag")
    first, second = lines(state_home)
    assert (first["caller"], first["session"]) == ("hermes", "env-session")
    assert second["caller"] == "flag"


def test_no_log_writes_nothing(tree, state_home):
    run(tree(FILES), "launch", "--no-log")
    assert not state_home.exists()


def test_library_calls_never_log(tree, state_home):
    find(tree(FILES), "launch")
    assert not state_home.exists()


def test_private_modes_and_a_masked_query(tree, state_home):
    secret = "to" + "ken=" + "hunter2" * 2
    run(tree(FILES), f"launch {secret}")
    (day,) = state_home.rglob("*.jsonl")
    assert day.stat().st_mode & 0o777 == 0o600
    assert day.parent.stat().st_mode & 0o777 == 0o700
    assert "hunter2" not in day.read_text("utf-8")


def test_a_long_line_drops_ranked_entries_from_the_end(tree):
    root = tree({f"n{i}.md": "word\n" for i in range(30)})
    cfg = load(root, "[find.log]\nmax_line_bytes = 600\nlog_top = 30\n")
    result = run_find(cfg, "word")
    settings = find_settings(cfg)
    record = qlog.make_record(
        cfg, settings, result, caller="c", session=None, scope="all", limit=10, now=NOW
    )
    full = [row[0] for row in record["ranked"]]
    data = qlog.encode(record, 600)
    assert len(data) <= 600 and data.endswith(b"\n")
    kept = json.loads(data)["ranked"]
    assert 0 < len(kept) < 30
    assert [row[0] for row in kept] == full[: len(kept)]


def test_log_top_limits_ranked(tree, state_home):
    root = tree(
        {f"n{i}.md": "word\n" for i in range(8)} | {"shck.toml": "[find.log]\nlog_top = 3\n"}
    )
    run(root, "word", "--limit", "8")
    assert len(lines(state_home)[0]["ranked"]) == 3


def test_daily_size_cap_writes_one_truncated_marker(tree, state_home):
    root = tree(FILES | {"shck.toml": "[find.log]\nmax_bytes_per_day = 300\n"})
    for _ in range(5):
        run(root, "launch")
    (day,) = state_home.rglob("*.jsonl")
    rows = [json.loads(line) for line in day.read_text("utf-8").splitlines()]
    assert sum(1 for r in rows if r.get("truncated")) == 1 and rows[-1] == {"truncated": True}
    assert day.stat().st_size <= 300 + len(qlog.TRUNCATED)


def test_failure_prints_one_line_and_find_still_works(tree, state_home, tmp_path, capsys):
    state_home.parent.mkdir(exist_ok=True)
    state_home.write_text("a file, not a folder", encoding="utf-8")
    assert run(tree(FILES), "launch") == 0
    captured = capsys.readouterr()
    assert "1. " in captured.out
    assert captured.err.count("query log not written") == 1


def test_old_day_files_are_compressed_in_place_and_nothing_is_lost(tmp_path):
    folder = tmp_path / "queries"
    folder.mkdir()
    old = folder / "2026-07-01.jsonl"
    keep = folder / "2026-09-30.jsonl"
    old.write_text('{"v":1,"query":"old"}\n', encoding="utf-8")
    keep.write_text('{"v":1,"query":"recent"}\n', encoding="utf-8")
    done = qlog.compress_old(folder, 90, date(2026, 10, 31))
    assert [p.name for p in done] == ["2026-07-01.jsonl.gz"]
    assert not old.exists() and keep.exists()
    assert gzip.decompress((folder / "2026-07-01.jsonl.gz").read_bytes()) == (
        b'{"v":1,"query":"old"}\n'
    )
    assert sorted(p.name for p in folder.iterdir()) == ["2026-07-01.jsonl.gz", "2026-09-30.jsonl"]


def test_a_day_that_was_compressed_and_written_again_keeps_both_parts(tmp_path):
    folder = tmp_path / "queries"
    folder.mkdir()
    (folder / "2026-07-01.jsonl").write_bytes(b"one\n")
    qlog.compress_old(folder, 90, date(2026, 10, 31))
    (folder / "2026-07-01.jsonl").write_bytes(b"two\n")
    qlog.compress_old(folder, 90, date(2026, 10, 31))
    assert gzip.decompress((folder / "2026-07-01.jsonl.gz").read_bytes()) == b"one\ntwo\n"
    assert [p.name for p in folder.iterdir()] == ["2026-07-01.jsonl.gz"]


def test_a_find_call_compresses_old_days(tree, state_home):
    root = tree(FILES)
    run(root, "launch")
    (today_file,) = state_home.rglob("*.jsonl")
    old = today_file.parent / "2020-01-01.jsonl"
    old.write_text('{"v":1}\n', encoding="utf-8")
    run(root, "launch")
    assert not old.exists() and (today_file.parent / "2020-01-01.jsonl.gz").exists()


def test_keep_days_is_a_profile_key(tmp_path):
    folder = tmp_path / "q"
    folder.mkdir()
    (folder / "2026-10-20.jsonl").write_text("x\n", encoding="utf-8")
    assert qlog.compress_old(folder, 30, date(2026, 10, 31)) == []
    assert len(qlog.compress_old(folder, 5, date(2026, 10, 31))) == 1


def test_concurrent_appends_never_interleave(tmp_path):
    folder = tmp_path / "queries"
    payload = [json.dumps({"i": i, "pad": "x" * 3000}).encode() + b"\n" for i in range(8)]

    def work(data):
        for _ in range(25):
            qlog.append(folder, data, date(2026, 10, 31), 10_000_000)

    threads = [threading.Thread(target=work, args=(data,)) for data in payload]
    [t.start() for t in threads]
    [t.join() for t in threads]
    rows = (folder / "2026-10-31.jsonl").read_text("utf-8").splitlines()
    assert len(rows) == 200 and all(json.loads(row)["pad"] == "x" * 3000 for row in rows)
