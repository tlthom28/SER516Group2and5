import os
import subprocess
import pytest

from src.metrics.git_history import get_commit_history


def _run(cmd: list[str], cwd: str, env: dict | None = None) -> None:
    full_env = {**os.environ, **(env or {})}
    subprocess.run(cmd, cwd=cwd, env=full_env, check=True, capture_output=True)


def _make_repo_with_commits(tmp: str) -> list[str]:
    _run(["git", "init"], cwd=tmp)
    _run(["git", "config", "user.email", "test@example.com"], cwd=tmp)
    _run(["git", "config", "user.name", "Test"], cwd=tmp)

    shas: list[str] = []
    dates = [
        "2026-01-31T12:00:00+00:00",
        "2026-02-01T12:00:00+00:00",
        "2026-02-02T12:00:00+00:00",
    ]

    for i, iso in enumerate(dates):
        filepath = os.path.join(tmp, f"file{i}.txt")
        with open(filepath, "w") as f:
            f.write(f"commit {i}\n")

        _run(["git", "add", "."], cwd=tmp)
        env = {"GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso}
        _run(["git", "commit", "-m", f"commit {i}"], cwd=tmp, env=env)

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp,
            capture_output=True,
            text=True,
            check=True,
        )
        shas.append(result.stdout.strip())

    return shas


class TestGetCommitHistory:

    def test_filters_commits_by_date_range(self, tmp_path):
        repo = str(tmp_path)
        shas = _make_repo_with_commits(repo)

        commits = get_commit_history(repo, "2026-02-01", "2026-02-02")

        returned_hashes = {c["hash"] for c in commits}

        assert shas[1] in returned_hashes
        assert shas[2] in returned_hashes
        assert shas[0] not in returned_hashes

        for c in commits:
            assert "2026-02-01" <= c["date"] <= "2026-02-02"

    def test_single_day_range(self, tmp_path):
        repo = str(tmp_path)
        shas = _make_repo_with_commits(repo)

        commits = get_commit_history(repo, "2026-02-01", "2026-02-01")

        assert len(commits) == 1
        assert commits[0]["hash"] == shas[1]
        assert commits[0]["date"] == "2026-02-01"

    def test_no_commits_in_range(self, tmp_path):
        repo = str(tmp_path)
        _make_repo_with_commits(repo)

        commits = get_commit_history(repo, "2030-01-01", "2030-12-31")

        assert commits == []

    def test_invalid_repo_path(self):
        with pytest.raises(ValueError, match="does not exist"):
            get_commit_history("/nonexistent/path", "2026-01-01", "2026-12-31")

    def test_not_a_git_repo(self, tmp_path):
        with pytest.raises(ValueError, match="Not a git repository"):
            get_commit_history(str(tmp_path), "2026-01-01", "2026-12-31")

    def test_start_after_end_raises(self, tmp_path):
        repo = str(tmp_path)
        _make_repo_with_commits(repo)

        with pytest.raises(ValueError, match="must be <="):
            get_commit_history(repo, "2026-03-01", "2026-01-01")

    def test_invalid_date_format(self, tmp_path):
        repo = str(tmp_path)
        _make_repo_with_commits(repo)

        with pytest.raises(ValueError, match="Invalid start_date"):
            get_commit_history(repo, "not-a-date", "2026-01-01")

        with pytest.raises(ValueError, match="Invalid end_date"):
            get_commit_history(repo, "2026-01-01", "bad")