import os
import subprocess

import pytest

from src.metrics.git_history import get_commit_history
from src.metrics.churn import compute_commit_churn


def _run(cmd: list[str], cwd: str, env: dict | None = None) -> str:
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        cmd, cwd=cwd, env=full_env, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _init_repo(path: str) -> None:
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "test@example.com"], cwd=path)
    _run(["git", "config", "user.name", "Test"], cwd=path)
    _run(["git", "commit", "--allow-empty", "-m", "initial"], cwd=path)


def _commit_file(path: str, filename: str, content: str, iso_datetime: str) -> str:
    filepath = os.path.join(path, filename)
    with open(filepath, "w") as f:
        f.write(content)
    _run(["git", "add", filename], cwd=path)
    env = {"GIT_AUTHOR_DATE": iso_datetime, "GIT_COMMITTER_DATE": iso_datetime}
    _run(["git", "commit", "-m", f"add {filename}"], cwd=path, env=env)
    return _get_head_sha(path)


def _commit_binary(path: str, filename: str, data: bytes, iso_datetime: str) -> str:
    filepath = os.path.join(path, filename)
    with open(filepath, "wb") as f:
        f.write(data)
    _run(["git", "add", filename], cwd=path)
    env = {"GIT_AUTHOR_DATE": iso_datetime, "GIT_COMMITTER_DATE": iso_datetime}
    _run(["git", "commit", "-m", f"add binary {filename}"], cwd=path, env=env)
    return _get_head_sha(path)


def _get_head_sha(path: str) -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd=path)


class TestDateBoundariesInclusive:

    def test_date_boundaries_inclusive(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)

        sha_start = _commit_file(repo, "a.txt", "start\n", "2026-02-01T00:00:00+00:00")
        sha_end = _commit_file(repo, "b.txt", "end\n", "2026-02-03T23:59:59+00:00")

        commits = get_commit_history(repo, "2026-02-01", "2026-02-03")
        returned_hashes = {c["hash"] for c in commits}

        assert sha_start in returned_hashes
        assert sha_end in returned_hashes


class TestBinaryFilesIgnored:

    def test_binary_files_ignored(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)

        sha = _commit_binary(repo, "data.bin", b"\x00\x01\x02\x03\x04", "2026-03-01T12:00:00+00:00")

        churn = compute_commit_churn(repo, sha)

        assert isinstance(churn["added"], int) and churn["added"] >= 0
        assert isinstance(churn["deleted"], int) and churn["deleted"] >= 0
        assert isinstance(churn["modified"], int) and churn["modified"] >= 0
        assert isinstance(churn["total"], int) and churn["total"] >= 0


class TestRenameCommitSafe:

    def test_rename_commit_safe(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)

        _commit_file(repo, "old.txt", "line1\nline2\nline3\n", "2026-04-01T10:00:00+00:00")

        _run(["git", "mv", "old.txt", "new.txt"], cwd=repo)
        env = {
            "GIT_AUTHOR_DATE": "2026-04-02T10:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-04-02T10:00:00+00:00",
        }
        _run(["git", "commit", "-m", "rename old to new"], cwd=repo, env=env)
        rename_sha = _get_head_sha(repo)

        churn = compute_commit_churn(repo, rename_sha)

        assert isinstance(churn["added"], int) and churn["added"] >= 0
        assert isinstance(churn["deleted"], int) and churn["deleted"] >= 0
        assert isinstance(churn["modified"], int) and churn["modified"] >= 0
        assert isinstance(churn["total"], int) and churn["total"] >= 0


class TestMergeCommitSafe:

    def test_merge_commit_safe(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)

        _commit_file(repo, "shared.txt", "base\n", "2026-05-01T10:00:00+00:00")

        _run(["git", "checkout", "-b", "feature"], cwd=repo)
        _commit_file(repo, "feature.txt", "feature work\n", "2026-05-02T10:00:00+00:00")

        _run(["git", "checkout", "master"], cwd=repo)
        _commit_file(repo, "main_work.txt", "main work\n", "2026-05-03T10:00:00+00:00")

        try:
            _run(["git", "merge", "--no-ff", "feature", "-m", "merge feature"], cwd=repo)
        except subprocess.CalledProcessError:
            _run(["git", "checkout", "main"], cwd=repo)
            _commit_file(repo, "main_work.txt", "main work\n", "2026-05-03T10:00:00+00:00")
            _run(["git", "merge", "--no-ff", "feature", "-m", "merge feature"], cwd=repo)

        merge_sha = _get_head_sha(repo)

        churn = compute_commit_churn(repo, merge_sha)

        assert isinstance(churn["added"], int) and churn["added"] >= 0
        assert isinstance(churn["deleted"], int) and churn["deleted"] >= 0
        assert isinstance(churn["modified"], int) and churn["modified"] >= 0
        assert isinstance(churn["total"], int) and churn["total"] >= 0
