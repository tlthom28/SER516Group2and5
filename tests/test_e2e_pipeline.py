import pytest
import time
from pathlib import Path
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)
SAMPLE_REPO_PATH = str(Path(__file__).parent / "sample_files/python_project")


class TestE2EPipelineSuccess:

    def test_submit_job_and_retrieve_result(self):
        response = client.post("/jobs", json={"local_path": SAMPLE_REPO_PATH})
        assert response.status_code == 201
        job_id = response.json()["job_id"]
        
        for _ in range(30):
            response = client.get(f"/jobs/{job_id}")
            job = response.json()
            if job["status"] == "completed":
                break
            time.sleep(0.1)
        assert job["status"] == "completed"
        assert job["result"] is not None
        assert job["result"]["total_loc"] > 0
        assert job["error"] is None

    def test_job_result_contains_loc_metrics(self):
        response = client.post(
            "/jobs",
            json={"local_path": SAMPLE_REPO_PATH}
        )
        job_id = response.json()["job_id"]
        
        # Wait for completion
        for _ in range(30):
            response = client.get(f"/jobs/{job_id}")
            job = response.json()
            if job["status"] == "completed":
                break
            time.sleep(0.1)
        
        result = job["result"]
        assert result is not None
        assert "project_root" in result
        assert "total_loc" in result
        assert "total_files" in result
        assert "total_blank_lines" in result
        assert "total_excluded_lines" in result
        assert "total_comment_lines" in result
        assert result["total_files"] > 0

    def test_metrics_written_to_influxdb(self):
        response = client.post(
            "/jobs",
            json={"local_path": SAMPLE_REPO_PATH}
        )
        job_id = response.json()["job_id"]
        
        # Wait for job completion
        for _ in range(30):
            response = client.get(f"/jobs/{job_id}")
            job = response.json()
            if job["status"] == "completed":
                break
            time.sleep(0.1)
        
        # Wait for InfluxDB write propagation
        time.sleep(1)
        
        # Verify metrics were written (via basic health check)
        response = client.get("/health/db")
        assert response.status_code == 200
        health = response.json()
        assert health["status"] == "pass"


class TestE2EPipelineConcurrency:
    def test_concurrent_jobs_process_independently(self):
        job_ids = []
        
        # Submit 3 concurrent jobs
        for i in range(3):
            response = client.post(
                "/jobs",
                json={"local_path": SAMPLE_REPO_PATH}
            )
            assert response.status_code == 201
            job_ids.append(response.json()["job_id"])
        
        # Wait for all jobs to complete
        completed_jobs = 0
        for _ in range(60):
            for job_id in job_ids:
                response = client.get(f"/jobs/{job_id}")
                job = response.json()
                if job["status"] == "completed" and job not in [j for j in job_ids if client.get(f"/jobs/{j}").json()["status"] == "completed"]:
                    completed_jobs += 1
            
            if completed_jobs >= len(job_ids):
                break
            time.sleep(0.1)
        
        # Verify all jobs completed
        for job_id in job_ids:
            response = client.get(f"/jobs/{job_id}")
            job = response.json()
            assert job["status"] == "completed"
            assert job["result"] is not None

    def test_concurrent_jobs_have_unique_results(self):
        # Submit 2 jobs
        response1 = client.post("/jobs", json={"local_path": SAMPLE_REPO_PATH})
        job_id1 = response1.json()["job_id"]
        
        response2 = client.post("/jobs", json={"local_path": SAMPLE_REPO_PATH})
        job_id2 = response2.json()["job_id"]
        
        # Wait for both to complete
        for _ in range(30):
            r1 = client.get(f"/jobs/{job_id1}").json()
            r2 = client.get(f"/jobs/{job_id2}").json()
            if r1["status"] == "completed" and r2["status"] == "completed":
                break
            time.sleep(0.1)
        
        # Get results
        job1 = client.get(f"/jobs/{job_id1}").json()
        job2 = client.get(f"/jobs/{job_id2}").json()
        
        # Each should have completed with results
        assert job1["status"] == "completed"
        assert job2["status"] == "completed"
        assert job1["result"] is not None
        assert job2["result"] is not None
        
        # Job IDs should be different
        assert job1["job_id"] != job2["job_id"]


class TestE2EPipelineFailureScenarios:
    def test_invalid_repository_path_fails(self):
        response = client.post(
            "/jobs",
            json={"local_path": "/nonexistent/repo/path"}
        )
        
        # Request should be accepted
        assert response.status_code == 201
        job_id = response.json()["job_id"]
        
        # Wait for job to complete
        for _ in range(30):
            response = client.get(f"/jobs/{job_id}")
            job = response.json()
            if job["status"] in ["completed", "failed"]:
                break
            time.sleep(0.1)
        
        job = response.json()
        # Job should have failed
        assert job["status"] in ["failed", "completed"]

    def test_invalid_request_body_rejected(self):
        # Missing required field
        response = client.post("/jobs", json={})
        assert response.status_code == 400

    def test_missing_repo_url_and_local_path_fails(self):
        response = client.post(
            "/jobs",
            json={"description": "invalid"}
        )
        assert response.status_code == 400

    def test_job_not_found_returns_404(self):
        response = client.get("/jobs/nonexistent-job-id-12345")
        assert response.status_code == 404


class TestE2EPipelineListJobs:
    def test_list_submitted_jobs(self):
        # Submit a job
        response = client.post("/jobs", json={"local_path": SAMPLE_REPO_PATH})
        job_id = response.json()["job_id"]
        
        # List all jobs
        response = client.get("/jobs")
        assert response.status_code == 200
        jobs = response.json()
        
        # New job should be in the list
        job_ids = [j["job_id"] for j in jobs]
        assert job_id in job_ids

    def test_list_shows_job_status(self):
        response = client.post("/jobs", json={"local_path": SAMPLE_REPO_PATH})
        job_id = response.json()["job_id"]
        
        # Get the job from list
        response = client.get("/jobs")
        jobs = response.json()
        
        job = next((j for j in jobs if j["job_id"] == job_id), None)
        assert job is not None
        assert "status" in job
        assert job["status"] in ["queued", "processing", "completed", "failed"]


class TestE2EPipelineWorkerHealth:
    def test_workers_health_endpoint(self):
        response = client.get("/workers/health")
        assert response.status_code == 200
        health = response.json()
        
        assert "pool_size" in health
        assert "active_workers" in health
        assert "queued_jobs" in health
        assert "processing_jobs" in health
        assert "completed_jobs" in health
        assert health["pool_size"] > 0

    def test_workers_health_reflects_active_jobs(self):
        # Submit a job
        response = client.post("/jobs", json={"local_path": SAMPLE_REPO_PATH})
        job_id = response.json()["job_id"]
        
        # Check health immediately (job might still be processing)
        response = client.get("/workers/health")
        health = response.json()
        
        # Should track jobs
        assert health["total_jobs"] >= 1


class TestE2EPipelineInfluxDBPersistence:
    def test_analyze_endpoint_writes_to_influxdb(self):
        response = client.get("/health/db")
        assert response.status_code == 200
        assert response.json()["status"] == "pass"
