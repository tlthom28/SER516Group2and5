import pytest
import time
from datetime import datetime, timezone
from src.core.influx import (
    get_client,
    write_loc_metric,
    write_churn_metric,
    write_daily_churn_metrics,
    query_flux,
)


class TestInfluxDBMetricWrite:

    def test_write_loc_metric_succeeds(self):
        metric = {"repo_id": "test-influx-001", "repo_name": "test", "branch": "main",
                  "language": "python", "granularity": "project", "total_loc": 1500,
                  "code_loc": 1200, "comment_loc": 200, "blank_loc": 100,
                  "collected_at": datetime.now(timezone.utc).isoformat()}
        write_loc_metric(metric)
        time.sleep(0.5)

    def test_write_churn_metric_succeeds(self):
        churn = {
            "added": 150,
            "deleted": 50,
            "modified": 50,
            "total": 200,
        }
        
        write_churn_metric(
            repo_url="https://github.com/test/repo.git",
            start_date="2026-02-01",
            end_date="2026-02-28",
            churn=churn
        )
        time.sleep(0.5)

    def test_write_daily_churn_metrics_succeeds(self):
        daily_churn = {
            "2026-02-01": {
                "added": 50,
                "deleted": 20,
                "modified": 20,
                "total": 70,
            },
            "2026-02-02": {
                "added": 75,
                "deleted": 30,
                "modified": 30,
                "total": 105,
            },
        }
        
        write_daily_churn_metrics(
            repo_url="https://github.com/test/repo.git",
            daily=daily_churn
        )
        time.sleep(0.5)


class TestInfluxDBMetricWriteVariations:
    def test_write_file_level_metric(self):
        metric = {
            "repo_id": "test-file-level-001",
            "repo_name": "test-repo",
            "branch": "main",
            "language": "python",
            "granularity": "file",
            "file_path": "src/main.py",
            "total_loc": 250,
            "code_loc": 200,
            "comment_loc": 30,
            "blank_loc": 20,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
        
        write_loc_metric(metric)
        time.sleep(0.5)

    def test_write_package_level_metric(self):
        metric = {
            "repo_id": "test-package-level-001",
            "repo_name": "test-repo",
            "branch": "main",
            "language": "mixed",
            "granularity": "package",
            "package_name": "src.utils",
            "total_loc": 500,
            "code_loc": 400,
            "comment_loc": 70,
            "blank_loc": 30,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
        
        write_loc_metric(metric)
        time.sleep(0.5)

    def test_multiple_writes_same_repo(self):
        repo_id = "test-multi-write-001"
        
        for i in range(3):
            metric = {
                "repo_id": repo_id,
                "repo_name": "multi-test",
                "branch": "main",
                "language": "python",
                "granularity": "project",
                "total_loc": 1000 + (i * 100),
                "code_loc": 800 + (i * 80),
                "comment_loc": 150,
                "blank_loc": 50,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
            write_loc_metric(metric)
            time.sleep(0.1)


class TestInfluxDBHealth:
    def test_client_initialized(self):
        client = get_client()
        assert client is not None

    def test_client_health_check(self):
        client = get_client()
        health = client.health()
        assert health is not None

    def test_write_and_health(self):
        metric = {
            "repo_id": "test-health-001",
            "repo_name": "health-repo",
            "branch": "main",
            "language": "python",
            "granularity": "project",
            "total_loc": 500,
            "code_loc": 400,
            "comment_loc": 75,
            "blank_loc": 25,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
        
        write_loc_metric(metric)
        time.sleep(0.5)
        
        # Verify client is still responsive
        client = get_client()
        health = client.health()
        assert health is not None

