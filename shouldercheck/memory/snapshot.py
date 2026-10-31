"""Read a record base as it was at a git commit, without touching the repository.

`git archive` is read-only and works on a bare history repository used with a separate work
tree; `git worktree add` would write metadata into that repository.
"""

import os
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


class SnapshotError(Exception):
    """The commit, the repository or the git program is unusable (exit 3)."""


def _git(git_dir: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "--git-dir", str(git_dir), *args],
            capture_output=True,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except OSError as exc:
        raise SnapshotError(f"cannot run git: {exc}") from exc


def tree_hash(git_dir: Path, commit: str) -> str:
    done = _git(git_dir, "rev-parse", "--verify", "--quiet", f"{commit}^{{tree}}")
    if done.returncode != 0:
        raise SnapshotError(f"snapshot {commit!r} not found in {git_dir.name}")
    return done.stdout.decode().strip()


def read_file(git_dir: Path, commit: str, rel: str) -> str | None:
    """One file of the snapshot, or None when the commit has no such file."""
    done = _git(git_dir, "show", f"{commit}:{rel}")
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None


def _safe(member: tarfile.TarInfo) -> PurePosixPath | None:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
        return None
    return path


def extract(git_dir: Path, commit: str, dest: Path) -> None:
    """Unpack the commit's files into `dest`; links and special files are skipped."""
    try:
        proc = subprocess.Popen(
            ["git", "--git-dir", str(git_dir), "archive", "--format=tar", commit],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise SnapshotError(f"cannot run git: {exc}") from exc
    assert proc.stdout is not None and proc.stderr is not None
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            for member in archive:
                path = _safe(member)
                if path is None:
                    continue
                target = dest / path
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(handle.read())
    except (tarfile.TarError, OSError) as exc:
        proc.kill()
        raise SnapshotError(f"cannot unpack snapshot {commit!r}: {exc}") from exc
    finally:
        message = proc.stderr.read().decode(errors="replace").strip()
        proc.stdout.close()
        proc.stderr.close()
        code = proc.wait()
    if code != 0:
        raise SnapshotError(f"git archive {commit!r} failed: {message[:200]}")
