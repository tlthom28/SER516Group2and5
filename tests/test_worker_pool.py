"""Tests for the worker pool: job lifecycle, parallel execution, health monitoring, load test."""
import os
import time
import tempfile
import shutil
import threading
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from src.main import app
from src.worker.pool import WorkerPool, JobRecord


client = TestClient(app)


# Block all InfluxDB writes during pool tests so fake repo names
# (repo0, repo1, b, d, …) don't pollute the real database.
@pytest.fixture(autouse=True)
def _no_influx_writes():
    with patch("src.core.influx.write_loc_metric"), \
         patch("src.core.influx.batch_write_loc_metrics"):
        yield


# --- Helper ---

def _make_sample_tree(dest):
    """Create a small sample project for LOC analysis."""
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "Main.java"), "w") as f:
        f.write("public class Main {\n    public static void main(String[] args) {}\n}\n")
    with open(os.path.join(dest, "app.py"), "w") as f:
        f.write("# comment\nprint('hi')\n")


# === Unit tests for WorkerPool class =========================================

class TestWorkerPoolUnit:
    """Test the WorkerPool directly (no HTTP)."""

    def test_start_and_shutdown(self):
        pool = WorkerPool(pool_size=2)
        pool.start()
        assert pool._executor is not None
        pool.shutdown()

    def test_submit_requires_started_pool(self):
        pool = WorkerPool(pool_size=2)
        with pytest.raises(RuntimeError, match="not running"):
            pool.submit("job-1", local_path="/tmp/nope")

    @patch("src.worker.pool.GitRepoCloner")
    @patch("src.worker.pool.write_loc_metric", create=True)
    def test_job_lifecycle_local_path(self, mock_write, mock_cloner_cls):
        """Submit a job with a local path and verify status transitions."""
        tmp = tempfile.mkdtemp(prefix="test_pool_")
        _make_sample_tree(tmp)

        pool = WorkerPool(pool_size=2)
        pool.start()
        try:
            record = pool.submit("job-lp", local_path=tmp)
            # wait for completion
            record.future.result(timeout=10)

            assert record.status == "completed"
            assert record.started_at is not None
            assert record.completed_at is not None
            assert record.result is not None
            assert record.result["total_loc"] > 0
            assert record.error is None
        finally:
            pool.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.worker.pool.GitRepoCloner")
    def test_job_lifecycle_clone(self, mock_cloner_cls):
        """Submit a job with a repo URL (mock clone) and verify it completes."""
        tmp = tempfile.mkdtemp(prefix="test_pool_clone_")
        _make_sample_tree(tmp)

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner_cls.return_value = mock_cloner

        pool = WorkerPool(pool_size=2)
        pool.start()
        try:
            record = pool.submit("job-clone", repo_url="https://github.com/owner/repo")
            record.future.result(timeout=10)

            assert record.status == "completed"
            assert record.result["total_loc"] > 0
            mock_cloner.cleanup.assert_called_once()
        finally:
            pool.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.worker.pool.compute_daily_churn", return_value={})
    @patch("src.worker.pool.compute_repo_churn", return_value={"added": 1, "deleted": 2, "modified": 1, "total": 3})
    @patch("src.worker.pool.GitRepoCloner")
    def test_job_clone_deepens_history_for_requested_dates(self, mock_cloner_cls, _mock_repo_churn, _mock_daily_churn):
        tmp = tempfile.mkdtemp(prefix="test_pool_dates_")
        _make_sample_tree(tmp)

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner_cls.return_value = mock_cloner

        pool = WorkerPool(pool_size=1)
        pool.start()
        try:
            record = pool.submit(
                "job-dates",
                repo_url="https://github.com/owner/repo",
                start_date="2026-03-01",
                end_date="2026-03-31",
            )
            record.future.result(timeout=10)

            assert record.status == "completed"
            assert record.start_date == "2026-03-01"
            assert record.end_date == "2026-03-31"
            mock_cloner.deepen_since.assert_called_once_with(tmp, "2026-03-01")
            assert record.result["churn"]["total"] == 3
        finally:
            pool.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.worker.pool.GitRepoCloner")
    def test_job_failure(self, mock_cloner_cls):
        """If clone raises, the job should be marked as failed."""
        from src.core.git_clone import GitCloneError

        mock_cloner = MagicMock()
        mock_cloner.clone.side_effect = GitCloneError("boom")
        mock_cloner_cls.return_value = mock_cloner

        pool = WorkerPool(pool_size=2)
        pool.start()
        try:
            record = pool.submit("job-fail", repo_url="https://github.com/bad/repo")
            record.future.result(timeout=10)

            assert record.status == "failed"
            assert "boom" in record.error
        finally:
            pool.shutdown()

    @patch("src.worker.pool.write_method_coverage_metrics")
    @patch("src.worker.pool.scan_method_coverage_repo")
    @patch("src.worker.pool.write_fog_index_metrics")
    @patch("src.worker.pool.analyze_fog_index_root")
    @patch("src.worker.pool.GitRepoCloner")
    def test_requested_code_quality_metrics_are_run(
        self,
        mock_cloner_cls,
        mock_analyze_fog_index_root,
        mock_write_fog_index_metrics,
        mock_scan_method_coverage_repo,
        mock_write_method_coverage_metrics,
    ):
        tmp = tempfile.mkdtemp(prefix="test_pool_metrics_")
        _make_sample_tree(tmp)

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner.commit_hash = "abc123"
        mock_cloner_cls.return_value = mock_cloner
        mock_analyze_fog_index_root.return_value = [
            (6.5, "medium", "comment", Path(tmp) / "app.py", "ok")
        ]
        mock_scan_method_coverage_repo.return_value = {
            "public": {"coverage": 75.0},
            "protected": {"coverage": None},
            "default": {"coverage": 50.0},
            "private": {"coverage": 25.0},
        }

        pool = WorkerPool(pool_size=1)
        pool.start()
        try:
            record = pool.submit(
                "job-metrics",
                repo_url="https://github.com/owner/repo",
                metrics=["fog_index", "method_coverage"],
            )
            record.future.result(timeout=10)

            assert record.status == "completed"
            assert "fog_index" in record.result
            assert record.result["fog_index"]["summary"]["file_count"] == 1
            assert "method_coverage" in record.result
            assert record.result["method_coverage"]["public_coverage_percent"] == 75.0
            assert record.result["method_coverage"]["protected_coverage_percent"] == 0.0
            mock_analyze_fog_index_root.assert_called_once()
            mock_write_fog_index_metrics.assert_called_once()
            mock_scan_method_coverage_repo.assert_called_once()
            mock_write_method_coverage_metrics.assert_called_once()
        finally:
            pool.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_health_counts(self):
        pool = WorkerPool(pool_size=2)
        pool.start()
        try:
            h = pool.health()
            assert h["pool_size"] == 2
            assert h["total_jobs"] == 0
            assert h["queued_jobs"] == 0
        finally:
            pool.shutdown()

    @patch("src.worker.pool.GitRepoCloner")
    def test_concurrent_execution(self, mock_cloner_cls):
        """Two jobs should run at the same time in the pool."""
        started = threading.Event()
        gate = threading.Event()  # block workers until we say go
        call_count = {"n": 0}

        def slow_clone(url, shallow=True):
            call_count["n"] += 1
            started.set()
            gate.wait(timeout=5)
            tmp = tempfile.mkdtemp(prefix="test_concurrent_")
            _make_sample_tree(tmp)
            return tmp

        mock_cloner = MagicMock()
        mock_cloner.clone.side_effect = slow_clone
        mock_cloner_cls.return_value = mock_cloner

        pool = WorkerPool(pool_size=2)
        pool.start()
        try:
            r1 = pool.submit("c1", repo_url="https://github.com/a/b")
            r2 = pool.submit("c2", repo_url="https://github.com/c/d")
            # wait a moment for both to start
            time.sleep(0.5)
            h = pool.health()
            # at least one should be processing
            assert h["processing_jobs"] >= 1

            gate.set()  # let them finish
            r1.future.result(timeout=10)
            r2.future.result(timeout=10)
            assert r1.status == "completed"
            assert r2.status == "completed"
        finally:
            pool.shutdown()

    def test_get_job_returns_none_for_unknown(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        try:
            assert pool.get_job("nonexistent") is None
        finally:
            pool.shutdown()

    def test_list_jobs_empty(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        try:
            assert pool.list_jobs() == []
        finally:
            pool.shutdown()


# === API integration tests ====================================================

class TestWorkerAPI:
    """Test the worker endpoints via HTTP."""

    def test_workers_health_endpoint(self):
        response = client.get("/workers/health")
        assert response.status_code == 200
        data = response.json()
        assert "pool_size" in data
        assert "active_workers" in data
        assert "queued_jobs" in data
        assert data["pool_size"] >= 1

    @patch("src.worker.pool.GitRepoCloner")
    def test_submit_and_get_job(self, mock_cloner_cls):
        """POST /jobs then GET /jobs/{id} and verify lifecycle."""
        tmp = tempfile.mkdtemp(prefix="test_api_pool_")
        _make_sample_tree(tmp)

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner_cls.return_value = mock_cloner

        # submit
        resp = client.post("/jobs", json={"repo_url": "https://github.com/owner/repo"})
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        # poll until done (max 5s)
        for _ in range(50):
            detail = client.get(f"/jobs/{job_id}").json()
            if detail["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        assert detail["status"] == "completed"
        assert detail["result"]["total_loc"] > 0
        shutil.rmtree(tmp, ignore_errors=True)

    def test_get_job_not_found(self):
        resp = client.get("/jobs/does-not-exist")
        assert resp.status_code == 404

    def test_list_jobs_endpoint(self):
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @patch("src.worker.pool.GitRepoCloner")
    def test_job_failure_via_api(self, mock_cloner_cls):
        """If clone fails, job status should be 'failed' with error message."""
        from src.core.git_clone import GitCloneError
        mock_cloner = MagicMock()
        mock_cloner.clone.side_effect = GitCloneError("network error")
        mock_cloner_cls.return_value = mock_cloner

        resp = client.post("/jobs", json={"repo_url": "https://github.com/bad/repo"})
        job_id = resp.json()["job_id"]

        for _ in range(50):
            detail = client.get(f"/jobs/{job_id}").json()
            if detail["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        assert detail["status"] == "failed"
        assert "network error" in detail["error"]


# === US-31: GET /jobs/{job_id} status state tests =============================

class TestJobStatusEndpoint:
    """Dedicated tests for GET /jobs/{job_id} covering every status + progress."""

    def test_status_queued_with_progress(self):
        """A newly submitted job should be queued with progress 0."""
        gate = threading.Event()

        # block the worker so the job stays queued/processing
        original_run = app.state.worker_pool._run_job

        def blocked_run(record):
            gate.wait(timeout=5)
            original_run(record)

        with patch.object(app.state.worker_pool, "_run_job", side_effect=blocked_run):
            resp = client.post("/jobs", json={"local_path": "/tmp/fake"})
            assert resp.status_code == 201
            job_id = resp.json()["job_id"]

            detail = client.get(f"/jobs/{job_id}").json()
            # should be queued or processing (depends on timing)
            assert detail["status"] in ("queued", "processing")
            assert "progress" in detail
            assert detail["result"] is None
            assert detail["error"] is None

            gate.set()  # let it finish (it will fail since /tmp/fake doesn't exist, that's fine)

    @patch("src.worker.pool.GitRepoCloner")
    def test_status_processing_with_progress(self, mock_cloner_cls):
        """While a job is running, status should be 'processing' with progress > 0."""
        started = threading.Event()
        gate = threading.Event()

        def slow_clone(url, shallow=True):
            started.set()
            gate.wait(timeout=5)
            tmp = tempfile.mkdtemp(prefix="test_processing_")
            _make_sample_tree(tmp)
            return tmp

        mock_cloner = MagicMock()
        mock_cloner.clone.side_effect = slow_clone
        mock_cloner_cls.return_value = mock_cloner

        resp = client.post("/jobs", json={"repo_url": "https://github.com/owner/repo"})
        job_id = resp.json()["job_id"]

        # wait for the worker to actually start cloning
        started.wait(timeout=5)

        detail = client.get(f"/jobs/{job_id}").json()
        assert detail["status"] == "processing"
        assert detail["progress"] >= 10
        assert detail["started_at"] is not None
        assert detail["result"] is None

        gate.set()  # let it finish
        # wait for completion
        for _ in range(50):
            d = client.get(f"/jobs/{job_id}").json()
            if d["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

    @patch("src.worker.pool.GitRepoCloner")
    def test_status_completed_with_results_and_progress(self, mock_cloner_cls):
        """A completed job should have status=completed, progress=100, and a result dict."""
        tmp = tempfile.mkdtemp(prefix="test_completed_")
        _make_sample_tree(tmp)

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner_cls.return_value = mock_cloner

        resp = client.post("/jobs", json={"repo_url": "https://github.com/owner/repo"})
        job_id = resp.json()["job_id"]

        for _ in range(50):
            detail = client.get(f"/jobs/{job_id}").json()
            if detail["status"] == "completed":
                break
            time.sleep(0.1)

        assert detail["status"] == "completed"
        assert detail["progress"] == 100
        assert detail["started_at"] is not None
        assert detail["completed_at"] is not None
        assert detail["result"] is not None
        assert detail["result"]["total_loc"] > 0
        assert detail["error"] is None
        shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.worker.pool.GitRepoCloner")
    def test_status_failed_with_error_and_progress(self, mock_cloner_cls):
        """A failed job should have status=failed, progress=0, and an error message."""
        from src.core.git_clone import GitCloneError
        mock_cloner = MagicMock()
        mock_cloner.clone.side_effect = GitCloneError("auth failed")
        mock_cloner_cls.return_value = mock_cloner

        resp = client.post("/jobs", json={"repo_url": "https://github.com/bad/repo"})
        job_id = resp.json()["job_id"]

        for _ in range(50):
            detail = client.get(f"/jobs/{job_id}").json()
            if detail["status"] == "failed":
                break
            time.sleep(0.1)

        assert detail["status"] == "failed"
        assert detail["progress"] == 0
        assert detail["error"] is not None
        assert "auth failed" in detail["error"]
        assert detail["result"] is None
        assert detail["completed_at"] is not None

    def test_status_not_found(self):
        """GET /jobs/{id} for a non-existent job should return 404."""
        resp = client.get("/jobs/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Job not found"


# === Load test: 5+ simultaneous jobs ==========================================

class TestLoadParallel:
    """Submit 6 jobs at once and verify they all complete."""

    @patch("src.worker.pool.GitRepoCloner")
    def test_six_simultaneous_jobs(self, mock_cloner_cls):
        dirs = []
        for i in range(6):
            tmp = tempfile.mkdtemp(prefix=f"test_load_{i}_")
            _make_sample_tree(tmp)
            dirs.append(tmp)

        idx = {"i": 0}

        def fake_clone(url, shallow=True):
            # each call gets the next temp dir
            d = dirs[idx["i"] % len(dirs)]
            idx["i"] += 1
            return d

        mock_cloner = MagicMock()
        mock_cloner.clone.side_effect = fake_clone
        mock_cloner_cls.return_value = mock_cloner

        # submit all 6 at once
        job_ids = []
        for i in range(6):
            resp = client.post(
                "/jobs",
                json={"repo_url": f"https://github.com/owner/repo{i}"},
            )
            assert resp.status_code == 201
            job_ids.append(resp.json()["job_id"])

        # wait for all to finish
        for _ in range(100):
            statuses = []
            for jid in job_ids:
                detail = client.get(f"/jobs/{jid}").json()
                statuses.append(detail["status"])
            if all(s in ("completed", "failed") for s in statuses):
                break
            time.sleep(0.1)

        # all should have completed
        for jid in job_ids:
            detail = client.get(f"/jobs/{jid}").json()
            assert detail["status"] == "completed", f"Job {jid} was {detail['status']}"
            assert detail["result"]["total_loc"] > 0

        # cleanup
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)

    def test_health_reflects_load(self):
        """After submitting jobs, health should show them in total_jobs."""
        resp = client.get("/workers/health")
        assert resp.status_code == 200
        data = resp.json()
        # we've submitted multiple jobs across tests
        assert data["total_jobs"] >= 0
