import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def _run(cmd: list[str], cwd: str, env: dict | None = None) -> None:
    full_env = {**os.environ, **(env or {})}
    subprocess.run(cmd, cwd=cwd, env=full_env, check=True, capture_output=True)


def _create_test_repo(path: str) -> None:
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "test@example.com"], cwd=path)
    _run(["git", "config", "user.name", "Test"], cwd=path)

    filepath = os.path.join(path, "hello.py")
    with open(filepath, "w") as f:
        f.write("print('hello')\nprint('world')\n")

    env = {
        "GIT_AUTHOR_DATE": "2025-06-01T12:00:00",
        "GIT_COMMITTER_DATE": "2025-06-01T12:00:00",
    }
    _run(["git", "add", "."], cwd=path)
    _run(["git", "commit", "-m", "initial commit"], cwd=path, env=env)


class TestAnalyzeEndpoint:

    @patch("src.api.routes.write_daily_churn_metrics")
    @patch("src.api.routes.write_churn_metric")
    @patch("src.api.routes.write_loc_metric")
    @patch("src.api.routes.GitRepoCloner")
    def test_analyze_returns_loc_and_churn(
        self, mock_cloner_cls, mock_write_loc, mock_write_churn, mock_write_daily
    ):
        tmp_dir = tempfile.mkdtemp()

        try:
            _create_test_repo(tmp_dir)

            mock_cloner = MagicMock()
            mock_cloner.clone.return_value = tmp_dir
            mock_cloner.cleanup.return_value = None
            mock_cloner_cls.return_value = mock_cloner

            response = client.post(
                "/analyze",
                json={
                    "repo_url": "https://github.com/test/repo",
                    "start_date": "2000-01-01",
                    "end_date": "2100-01-01",
                },
            )

            assert response.status_code == 200

            data = response.json()

            assert "loc" in data
            assert data["loc"]["total_loc"] >= 2
            assert data["loc"]["total_files"] >= 1

            assert "churn" in data
            assert isinstance(data["churn"]["added"], int)
            assert isinstance(data["churn"]["deleted"], int)
            assert isinstance(data["churn"]["modified"], int)
            assert isinstance(data["churn"]["total"], int)
            assert data["churn"]["added"] >= 2

            assert data["start_date"] == "2000-01-01"
            assert data["end_date"] == "2100-01-01"
            assert data["repo_url"] == "https://github.com/test/repo"

            mock_write_loc.assert_called_once()
            mock_write_churn.assert_called_once()

        finally:
            subprocess.run(["rm", "-rf", tmp_dir], check=True, capture_output=True)

    @patch("src.api.routes.write_daily_churn_metrics")
    @patch("src.api.routes.write_churn_metric")
    @patch("src.api.routes.write_loc_metric")
    @patch("src.api.routes.GitRepoCloner")
    def test_analyze_defaults_date_range(
        self, mock_cloner_cls, mock_write_loc, mock_write_churn, mock_write_daily
    ):
        """When start_date/end_date are omitted, they should default to last 7 days."""
        tmp_dir = tempfile.mkdtemp()

        try:
            _create_test_repo(tmp_dir)

            mock_cloner = MagicMock()
            mock_cloner.clone.return_value = tmp_dir
            mock_cloner.cleanup.return_value = None
            mock_cloner_cls.return_value = mock_cloner

            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/test/repo"},
            )

            assert response.status_code == 200

            data = response.json()
            assert data["start_date"] is not None
            assert data["end_date"] is not None
            assert "loc" in data
            assert "churn" in data

        finally:
            subprocess.run(["rm", "-rf", tmp_dir], check=True, capture_output=True)

    def test_analyze_missing_repo_url(self):
        """POST /analyze with no repo_url should return 400."""
        response = client.post("/analyze", json={})

        assert response.status_code == 400

    @patch("src.api.routes.write_daily_churn_metrics")
    @patch("src.api.routes.write_churn_metric")
    @patch("src.api.routes.write_loc_metric")
    @patch("src.api.routes.GitRepoCloner")
    def test_analyze_influx_failure_does_not_break_response(
        self, mock_cloner_cls, mock_write_loc, mock_write_churn, mock_write_daily
    ):
        """Even if InfluxDB writes fail, the endpoint should still return 200."""
        tmp_dir = tempfile.mkdtemp()

        try:
            _create_test_repo(tmp_dir)

            mock_cloner = MagicMock()
            mock_cloner.clone.return_value = tmp_dir
            mock_cloner.cleanup.return_value = None
            mock_cloner_cls.return_value = mock_cloner

            mock_write_loc.side_effect = Exception("InfluxDB down")
            mock_write_churn.side_effect = Exception("InfluxDB down")
            mock_write_daily.side_effect = Exception("InfluxDB down")

            response = client.post(
                "/analyze",
                json={
                    "repo_url": "https://github.com/test/repo",
                    "start_date": "2000-01-01",
                    "end_date": "2100-01-01",
                },
            )

            assert response.status_code == 200

            data = response.json()
            assert "loc" in data
            assert "churn" in data

        finally:
            subprocess.run(["rm", "-rf", tmp_dir], check=True, capture_output=True)
