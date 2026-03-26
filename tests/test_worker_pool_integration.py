import pytest
import threading
import time
from pathlib import Path
from src.worker.pool import WorkerPool, JobRecord

# Use a sample repository from test fixtures
SAMPLE_REPO_PATH = str(Path(__file__).parent / "sample_files/python_project")


class TestWorkerPoolJobProcessing:

    def test_submit_job_with_local_path(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        
        try:
            record = pool.submit(
                job_id="test-job-001",
                local_path=SAMPLE_REPO_PATH
            )
            
            assert record.job_id == "test-job-001"
            assert record.status in ["queued", "processing"]
            assert record.local_path == SAMPLE_REPO_PATH
            assert record.repo_url is None
        finally:
            pool.shutdown()

    def test_job_completes_with_results(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        
        try:
            record = pool.submit(
                job_id="test-job-002",
                local_path=SAMPLE_REPO_PATH
            )
            
            for _ in range(30):
                if record.status == "completed":
                    break
                time.sleep(0.1)
            
            assert record.status == "completed"
            assert record.result and record.result["total_loc"] > 0
        finally:
            pool.shutdown()

    def test_job_result_structure(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        
        try:
            record = pool.submit(
                job_id="test-job-003",
                local_path=SAMPLE_REPO_PATH
            )
            
            for _ in range(30):
                if record.status == "completed":
                    break
                time.sleep(0.1)
            
            assert all(k in record.result for k in ["total_loc", "total_files", "total_blank_lines"])
        finally:
            pool.shutdown()


class TestWorkerPoolQueueing:

    def test_get_job_returns_record(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        
        try:
            pool.submit(
                job_id="test-job-queue-001",
                local_path=SAMPLE_REPO_PATH
            )
            
            record = pool.get_job("test-job-queue-001")
            assert record is not None
            assert record.job_id == "test-job-queue-001"
        finally:
            pool.shutdown()

    def test_list_jobs_includes_submitted_job(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        
        try:
            pool.submit(
                job_id="test-job-list-001",
                local_path=SAMPLE_REPO_PATH
            )
            
            jobs = pool.list_jobs()
            assert len(jobs) > 0
            job_ids = [j["job_id"] for j in jobs]
            assert "test-job-list-001" in job_ids
        finally:
            pool.shutdown()

    def test_job_status_transitions(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        
        try:
            record = pool.submit(
                job_id="test-job-status-001",
                local_path=SAMPLE_REPO_PATH
            )
            
            assert record.status in ["queued", "processing"]
            for _ in range(30):
                if record.status == "completed":
                    break
                time.sleep(0.1)
            assert record.status == "completed"
            assert record.started_at is not None
            assert record.completed_at is not None
        finally:
            pool.shutdown()


class TestWorkerPoolConcurrency:

    def test_concurrent_jobs_process_correctly(self):
        pool = WorkerPool(pool_size=4)  # 4 concurrent workers
        pool.start()
        
        try:
            job_ids = []
            for i in range(5):
                record = pool.submit(
                    job_id=f"test-concurrent-{i}",
                    local_path=SAMPLE_REPO_PATH
                )
                job_ids.append(record.job_id)
            
            # Wait for all jobs to complete
            completed = 0
            for _ in range(60):  # 6 second timeout
                completed_count = sum(
                    1 for jid in job_ids
                    if pool.get_job(jid).status == "completed"
                )
                if completed_count == len(job_ids):
                    break
                time.sleep(0.1)
            
            # All jobs should be completed
            for job_id in job_ids:
                record = pool.get_job(job_id)
                assert record.status == "completed"
                assert record.result is not None
        finally:
            pool.shutdown()

    def test_concurrent_jobs_have_different_results(self):
        pool = WorkerPool(pool_size=2)
        pool.start()
        
        try:

            record1 = pool.submit(
                job_id="test-concurrent-diff-1",
                local_path=SAMPLE_REPO_PATH
            )
            record2 = pool.submit(
                job_id="test-concurrent-diff-2",
                local_path=SAMPLE_REPO_PATH
            )
            

            for _ in range(30):
                if record1.status == "completed" and record2.status == "completed":
                    break
                time.sleep(0.1)
            
            # Each should have its own result object
            assert record1.result is not None
            assert record2.result is not None
            assert record1.result is not record2.result  # Different objects
            assert record1.job_id != record2.job_id  # Different job IDs
        finally:
            pool.shutdown()


class TestWorkerPoolHealth:

    def test_health_returns_pool_info(self):
        pool = WorkerPool(pool_size=4)
        pool.start()
        
        try:
            health = pool.health()
            
            assert "pool_size" in health
            assert "active_workers" in health
            assert "queued_jobs" in health
            assert "processing_jobs" in health
            assert "completed_jobs" in health
            assert health["pool_size"] == 4
        finally:
            pool.shutdown()

    def test_health_tracks_job_counts(self):
        pool = WorkerPool(pool_size=1)
        pool.start()
        
        try:

            pool.submit(
                job_id="test-health-001",
                local_path=SAMPLE_REPO_PATH
            )
            

            health = pool.health()
            assert health["total_jobs"] >= 1
            
            # Wait for completion
            for _ in range(30):
                record = pool.get_job("test-health-001")
                if record.status == "completed":
                    break
                time.sleep(0.1)
            

            health = pool.health()
            assert health["completed_jobs"] >= 1
        finally:
            pool.shutdown()
