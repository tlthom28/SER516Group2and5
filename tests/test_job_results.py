"""Tests for GET /jobs/{job_id}/results — result formatting, error handling, caching."""

import os
import time
import tempfile
import shutil
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.worker.pool import WorkerPool

client = TestClient(app)


# Block InfluxDB writes and churn subprocess calls during tests.
@pytest.fixture(autouse=True)
def _no_influx_writes():
    with patch("src.core.influx.write_loc_metric"):
        yield


def _make_sample_tree(dest):
    """Create a small sample project for LOC analysis."""
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "Main.java"), "w") as f:
        f.write(
            "// Main class\n"
            "public class Main {\n"
            "    public static void main(String[] args) {}\n"
            "}\n"
        )
    with open(os.path.join(dest, "app.py"), "w") as f:
        f.write("# comment\nprint('hi')\n")


# === Test: completed job returns structured LOC + Churn results ===============


class TestJobResultsEndpoint:
    """Tests for GET /jobs/{job_id}/results."""

    @patch("src.worker.pool.compute_repo_churn")
    @patch("src.worker.pool.GitRepoCloner")
    def test_completed_job_returns_loc_and_churn(self, mock_cloner_cls, mock_churn):
        """A completed job should return structured JSON with LOC metrics,
        churn metrics, and metadata."""
        tmp = tempfile.mkdtemp(prefix="test_results_")
        _make_sample_tree(tmp)

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner_cls.return_value = mock_cloner

        mock_churn.return_value = {
            "added": 10, "deleted": 3, "modified": 3, "total": 13,
        }

        # submit a job
        resp = client.post(
            "/jobs",
            json={"repo_url": "https://github.com/owner/repo"},
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        # wait for completion
        for _ in range(50):
            detail = client.get(f"/jobs/{job_id}").json()
            if detail["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)
        assert detail["status"] == "completed"

        # fetch results
        results = client.get(f"/jobs/{job_id}/results")
        assert results.status_code == 200

        data = results.json()

        # top-level fields
        assert data["job_id"] == job_id
        assert data["status"] == "completed"

        # metadata
        assert "metadata" in data
        assert data["metadata"]["repository"] == "https://github.com/owner/repo"
        assert data["metadata"]["scope"] == "project"
        assert data["metadata"]["analysed_at"]  # non-empty ISO timestamp

        # LOC section
        assert "loc" in data
        loc = data["loc"]
        assert loc["total_loc"] > 0
        assert loc["total_files"] >= 2
        assert isinstance(loc["total_blank_lines"], int)
        assert isinstance(loc["total_excluded_lines"], int)
        assert isinstance(loc["total_comment_lines"], int)
        assert isinstance(loc["total_weighted_loc"], float)
        assert loc["total_weighted_loc"] > 0

        # Churn section
        assert "churn" in data
        churn = data["churn"]
        assert churn["added"] == 10
        assert churn["deleted"] == 3
        assert churn["modified"] == 3
        assert churn["total"] == 13

        shutil.rmtree(tmp, ignore_errors=True)

    # === Test: non-existent job returns 404 ====================================

    def test_nonexistent_job_returns_404(self):
        """GET /jobs/{bad_id}/results should return 404 with error detail."""
        resp = client.get("/jobs/does-not-exist-xyz/results")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        assert data["detail"] == "Job not found"

    # === Test: pending / in-progress job returns status message =================

    @patch("src.worker.pool.compute_repo_churn")
    @patch("src.worker.pool.GitRepoCloner")
    def test_pending_job_returns_status_message(self, mock_cloner_cls, mock_churn):
        """A job that is still processing should return a message instead of results."""
        import threading

        gate = threading.Event()

        def slow_clone(url, shallow=True):
            gate.wait(timeout=10)
            tmp = tempfile.mkdtemp(prefix="test_pending_")
            _make_sample_tree(tmp)
            return tmp

        mock_cloner = MagicMock()
        mock_cloner.clone.side_effect = slow_clone
        mock_cloner_cls.return_value = mock_cloner

        resp = client.post(
            "/jobs",
            json={"repo_url": "https://github.com/owner/slow-repo"},
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        # give the worker a moment to start processing
        time.sleep(0.3)

        results = client.get(f"/jobs/{job_id}/results")
        assert results.status_code == 200

        data = results.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("queued", "processing")
        assert "message" in data
        assert "not available yet" in data["message"]

        # release the gate so the job can finish (cleanup)
        gate.set()

    # === Test: results are cached (repeated calls return same data) ============

    @patch("src.worker.pool.compute_repo_churn")
    @patch("src.worker.pool.GitRepoCloner")
    def test_results_cached_on_repeated_calls(self, mock_cloner_cls, mock_churn):
        """Calling GET /jobs/{job_id}/results twice should return the same data
        without re-computation (results are stored in the in-memory job record)."""
        tmp = tempfile.mkdtemp(prefix="test_cache_")
        _make_sample_tree(tmp)

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner_cls.return_value = mock_cloner

        mock_churn.return_value = {
            "added": 5, "deleted": 2, "modified": 2, "total": 7,
        }

        resp = client.post(
            "/jobs",
            json={"repo_url": "https://github.com/owner/cached-repo"},
        )
        job_id = resp.json()["job_id"]

        # wait for completion
        for _ in range(50):
            detail = client.get(f"/jobs/{job_id}").json()
            if detail["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        # first call
        r1 = client.get(f"/jobs/{job_id}/results")
        # second call
        r2 = client.get(f"/jobs/{job_id}/results")

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json()

        shutil.rmtree(tmp, ignore_errors=True)

    # === Test: failed job returns appropriate status ===========================

    @patch("src.worker.pool.GitRepoCloner")
    def test_failed_job_returns_status_message(self, mock_cloner_cls):
        """A failed job should return its status without crashing."""
        from src.core.git_clone import GitCloneError

        mock_cloner = MagicMock()
        mock_cloner.clone.side_effect = GitCloneError("clone failed")
        mock_cloner_cls.return_value = mock_cloner

        resp = client.post(
            "/jobs",
            json={"repo_url": "https://github.com/owner/bad-repo"},
        )
        job_id = resp.json()["job_id"]

        for _ in range(50):
            detail = client.get(f"/jobs/{job_id}").json()
            if detail["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        results = client.get(f"/jobs/{job_id}/results")
        assert results.status_code == 200

        data = results.json()
        assert data["job_id"] == job_id
        assert data["status"] == "failed"
        assert "not available yet" in data["message"]

    # === Test: local path job returns results with local_path as repository ====

    @patch("src.worker.pool.compute_repo_churn")
    @patch("src.worker.pool.GitRepoCloner")
    def test_local_path_job_metadata_uses_local_path(self, mock_cloner_cls, mock_churn):
        """When a job uses local_path, metadata.repository should reflect that."""
        tmp = tempfile.mkdtemp(prefix="test_local_results_")
        _make_sample_tree(tmp)

        mock_churn.return_value = {
            "added": 0, "deleted": 0, "modified": 0, "total": 0,
        }

        resp = client.post("/jobs", json={"local_path": tmp})
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        for _ in range(50):
            detail = client.get(f"/jobs/{job_id}").json()
            if detail["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        results = client.get(f"/jobs/{job_id}/results")
        assert results.status_code == 200

        data = results.json()
        assert data["metadata"]["repository"] == tmp

        shutil.rmtree(tmp, ignore_errors=True)
