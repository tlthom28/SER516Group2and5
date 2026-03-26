import os
import subprocess

import pytest

from src.metrics.churn import compute_commit_churn, compute_daily_churn


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


def _commit_file(path: str, filename: str, content: str, msg: str) -> str:
    filepath = os.path.join(path, filename)
    with open(filepath, "w") as f:
        f.write(content)
    _run(["git", "add", filename], cwd=path)
    _run(["git", "commit", "-m", msg], cwd=path)
    return _run(["git", "rev-parse", "HEAD"], cwd=path)


class TestComputeCommitChurn:
    def test_basic_addition(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)
        sha = _commit_file(repo, "hello.py", "print('hello')\nprint('world')\n", "add hello")

        churn = compute_commit_churn(repo, sha)

        assert churn["added"] == 2
        assert churn["deleted"] == 0
        assert churn["modified"] == 0
        assert churn["total"] == 2

    def test_three_lines_added(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)
        sha = _commit_file(
            repo,
            "utils.py",
            "def greet():\n    return 'hi'\n# end\n",
            "add 3 lines",
        )

        churn = compute_commit_churn(repo, sha)

        assert churn["added"] == 3
        assert churn["deleted"] == 0
        assert churn["modified"] == 0
        assert churn["total"] == 3

    def test_modification(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)
        _commit_file(repo, "app.py", "line1\nline2\nline3\n", "initial file")
        sha = _commit_file(repo, "app.py", "line1\nnew_a\nnew_b\nline3\n", "edit file")

        churn = compute_commit_churn(repo, sha)

        assert churn["added"] == 2
        assert churn["deleted"] == 1
        assert churn["modified"] == min(2, 1)
        assert churn["total"] == 3

    def test_empty_commit(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)
        _run(["git", "commit", "--allow-empty", "-m", "empty"], cwd=repo)
        sha = _run(["git", "rev-parse", "HEAD"], cwd=repo)

        churn = compute_commit_churn(repo, sha)

        assert churn == {"added": 0, "deleted": 0, "modified": 0, "total": 0}

    def test_invalid_repo_path(self):
        with pytest.raises(ValueError, match="does not exist"):
            compute_commit_churn("/nonexistent/path", "abc123")

    def test_not_a_git_repo(self, tmp_path):
        with pytest.raises(ValueError, match="Not a git repository"):
            compute_commit_churn(str(tmp_path), "abc123")

    def test_invalid_sha(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)

        with pytest.raises(ValueError, match="git show failed"):
            compute_commit_churn(repo, "0000000000000000000000000000000000000000")

    def test_binary_files_ignored(self, tmp_path):
        repo = str(tmp_path)
        _init_repo(repo)

        binpath = os.path.join(repo, "image.png")
        with open(binpath, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        _run(["git", "add", "image.png"], cwd=repo)
        _run(["git", "commit", "-m", "add binary"], cwd=repo)
        sha = _run(["git", "rev-parse", "HEAD"], cwd=repo)

        churn = compute_commit_churn(repo, sha)

        assert churn == {"added": 0, "deleted": 0, "modified": 0, "total": 0}


def _init_dated_repo(path: str) -> None:
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "test@example.com"], cwd=path)
    _run(["git", "config", "user.name", "Test"], cwd=path)
    _run(["git", "commit", "--allow-empty", "-m", "initial"], cwd=path)


def _commit_dated(path: str, filename: str, content: str, msg: str, iso_date: str) -> str:
    filepath = os.path.join(path, filename)
    with open(filepath, "w") as f:
        f.write(content)
    _run(["git", "add", filename], cwd=path)
    env = {"GIT_AUTHOR_DATE": iso_date, "GIT_COMMITTER_DATE": iso_date}
    _run(["git", "commit", "-m", msg], cwd=path, env=env)
    return _run(["git", "rev-parse", "HEAD"], cwd=path)


class TestComputeDailyChurn:

    def test_aggregates_multiple_commits_same_day(self, tmp_path):
        repo = str(tmp_path)
        _init_dated_repo(repo)

        _commit_dated(repo, "a.py", "line1\n", "add a", "2026-03-10T10:00:00")
        _commit_dated(repo, "b.py", "line1\nline2\n", "add b", "2026-03-10T14:00:00")
        _commit_dated(repo, "c.py", "x\n", "add c", "2026-03-11T09:00:00")

        daily = compute_daily_churn(repo, "2026-03-10", "2026-03-11")

        assert "2026-03-10" in daily
        assert "2026-03-11" in daily
        assert len(daily) == 2

        assert daily["2026-03-10"]["added"] == 3
        assert daily["2026-03-10"]["deleted"] == 0
        assert daily["2026-03-10"]["modified"] == 0
        assert daily["2026-03-10"]["total"] == 3

        assert daily["2026-03-11"]["added"] == 1
        assert daily["2026-03-11"]["total"] == 1

    def test_returns_empty_when_no_commits_in_range(self, tmp_path):
        repo = str(tmp_path)
        _init_dated_repo(repo)

        _commit_dated(repo, "a.py", "line1\n", "add a", "2026-03-10T10:00:00")

        daily = compute_daily_churn(repo, "2030-01-01", "2030-12-31")

        assert daily == {}