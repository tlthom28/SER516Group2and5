"""Tests for the InfluxDB write pipeline: batch writes, retry logic,
write confirmation/acknowledgment, error recovery, and performance benchmarking.

Covers acceptance criteria for US-42 (Data Pipeline from Workers to Time-Series DB).
"""
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call

import pytest

from src.core.influx import (
    WriteResult,
    _build_loc_point,
    _write_with_retry,
    write_loc_metric,
    batch_write_loc_metrics,
    write_churn_metric,
    write_daily_churn_metrics,
    write_taiga_metrics,
    write_cycle_time_metrics,
    BATCH_SIZE,
    MAX_RETRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_loc_metric(**overrides) -> dict:
    """Return a valid LOC metric dict with optional overrides."""
    base = {
        "repo_id": "https://github.com/owner/repo",
        "repo_name": "repo",
        "branch": "HEAD",
        "language": "python",
        "granularity": "file",
        "project_name": "repo",
        "file_path": "src/app.py",
        "total_loc": 100,
        "code_loc": 80,
        "comment_loc": 10,
        "blank_loc": 10,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


# =========================================================================
# 1. WriteResult model tests
# =========================================================================

class TestWriteResult:
    """Verify the WriteResult confirmation model."""

    def test_default_values(self):
        r = WriteResult(success=True)
        assert r.success is True
        assert r.points_written == 0
        assert r.points_failed == 0
        assert r.errors == []
        assert r.retries_used == 0

    def test_failure_result(self):
        r = WriteResult(success=False, points_failed=5, errors=["timeout"])
        assert r.success is False
        assert r.points_failed == 5
        assert "timeout" in r.errors


# =========================================================================
# 2. Point builder tests
# =========================================================================

class TestBuildLocPoint:
    """Ensure _build_loc_point produces valid InfluxDB Points."""

    def test_builds_point_with_all_tags(self):
        metric = _sample_loc_metric()
        point = _build_loc_point(metric)
        line = point.to_line_protocol()
        assert "loc_metrics" in line
        assert "repo_name=repo" in line
        assert "total_loc=100i" in line

    def test_builds_point_with_missing_optional_tags(self):
        metric = _sample_loc_metric()
        # package_name is not in the file-level sample — verify it's absent from the point
        point = _build_loc_point(metric)
        line = point.to_line_protocol()
        assert "package_name" not in line

    def test_handles_non_integer_fields_gracefully(self):
        metric = _sample_loc_metric(total_loc="not_a_number")
        point = _build_loc_point(metric)
        line = point.to_line_protocol()
        # should fall back to 0 on conversion error
        assert "total_loc=0i" in line


# =========================================================================
# 3. Single write with retry
# =========================================================================

class TestWriteLocMetric:
    """Test write_loc_metric: single point write with retry & confirmation."""

    @patch("src.core.influx.get_client")
    def test_successful_write_returns_confirmation(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        result = write_loc_metric(_sample_loc_metric())

        assert isinstance(result, WriteResult)
        assert result.success is True
        assert result.points_written == 1
        assert result.points_failed == 0
        assert result.retries_used == 0
        mock_write_api.write.assert_called_once()

    @patch("src.core.influx.get_client")
    def test_write_retries_on_failure(self, mock_get_client):
        """Should retry MAX_RETRIES times before giving up."""
        mock_write_api = MagicMock()
        mock_write_api.write.side_effect = Exception("connection refused")
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        # speed up retries for test
        with patch("src.core.influx.RETRY_BACKOFF_BASE", 0.01):
            result = write_loc_metric(_sample_loc_metric())

        assert result.success is False
        assert result.points_failed == 1
        assert result.retries_used == MAX_RETRIES
        assert len(result.errors) == MAX_RETRIES + 1
        assert mock_write_api.write.call_count == MAX_RETRIES + 1

    @patch("src.core.influx.get_client")
    def test_write_succeeds_after_transient_failure(self, mock_get_client):
        """Retry should recover from a transient error."""
        mock_write_api = MagicMock()
        # fail twice, then succeed
        mock_write_api.write.side_effect = [
            Exception("timeout"),
            Exception("timeout"),
            None,
        ]
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        with patch("src.core.influx.RETRY_BACKOFF_BASE", 0.01):
            result = write_loc_metric(_sample_loc_metric())

        assert result.success is True
        assert result.points_written == 1
        assert result.retries_used == 2
        assert len(result.errors) == 2  # two transient failures logged


# =========================================================================
# 4. Batch write tests
# =========================================================================

class TestBatchWriteLocMetrics:
    """Test batch_write_loc_metrics: batching, chunking, retry, confirmation."""

    @patch("src.core.influx.get_client")
    def test_batch_write_empty_list(self, mock_get_client):
        result = batch_write_loc_metrics([])
        assert result.success is True
        assert result.points_written == 0
        mock_get_client.assert_not_called()

    @patch("src.core.influx.get_client")
    def test_batch_write_multiple_points(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        metrics = [_sample_loc_metric(file_path=f"src/file_{i}.py") for i in range(10)]
        result = batch_write_loc_metrics(metrics)

        assert result.success is True
        assert result.points_written == 10
        assert result.points_failed == 0
        mock_write_api.write.assert_called_once()  # all in one batch (< BATCH_SIZE)

    @patch("src.core.influx.get_client")
    def test_batch_write_chunks_large_payloads(self, mock_get_client):
        """When len(metrics) > BATCH_SIZE, points should be sent in chunks."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        count = BATCH_SIZE + 50  # just over one batch
        metrics = [_sample_loc_metric(file_path=f"src/file_{i}.py") for i in range(count)]
        result = batch_write_loc_metrics(metrics)

        assert result.success is True
        assert result.points_written == count
        # should have been 2 write calls (one full batch + one remainder)
        assert mock_write_api.write.call_count == 2

    @patch("src.core.influx.get_client")
    def test_batch_write_partial_failure(self, mock_get_client):
        """If one chunk fails after all retries, the rest should still be written."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        # first chunk succeeds, second always fails
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            points = kwargs.get("record") or args[0] if args else []
            # first call (batch 1) succeeds, all others fail
            if call_count["n"] == 1:
                return None
            raise Exception("disk full")

        mock_write_api.write.side_effect = side_effect

        count = BATCH_SIZE + 10
        metrics = [_sample_loc_metric(file_path=f"src/file_{i}.py") for i in range(count)]

        with patch("src.core.influx.RETRY_BACKOFF_BASE", 0.01):
            result = batch_write_loc_metrics(metrics)

        assert result.success is False  # overall failure
        assert result.points_written == BATCH_SIZE  # first chunk succeeded
        assert result.points_failed == 10  # second chunk failed
        assert len(result.errors) > 0

    @patch("src.core.influx.get_client")
    def test_batch_write_returns_aggregate_retries(self, mock_get_client):
        """Aggregate retries_used should be the max across chunks."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # first batch call: fail once then succeed
                raise Exception("transient")

        mock_write_api.write.side_effect = [
            Exception("transient"),  # chunk 1 attempt 1
            None,                    # chunk 1 attempt 2 succeeds
        ]

        metrics = [_sample_loc_metric(file_path=f"src/file_{i}.py") for i in range(5)]

        with patch("src.core.influx.RETRY_BACKOFF_BASE", 0.01):
            result = batch_write_loc_metrics(metrics)

        assert result.success is True
        assert result.retries_used == 1  # recovered after 1 retry


# =========================================================================
# 5. Churn write tests (with retry)
# =========================================================================

class TestChurnWrites:
    """Churn write functions should also return WriteResult with retry."""

    @patch("src.core.influx.get_client")
    def test_write_churn_metric_confirmation(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        result = write_churn_metric(
            "https://github.com/owner/repo",
            "2025-01-01", "2025-01-31",
            {"added": 100, "deleted": 20, "modified": 30, "total": 150},
        )

        assert isinstance(result, WriteResult)
        assert result.success is True
        assert result.points_written == 1

    @patch("src.core.influx.get_client")
    def test_write_daily_churn_batch(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        daily = {
            "2025-01-01": {"added": 10, "deleted": 2, "modified": 3, "total": 15},
            "2025-01-02": {"added": 20, "deleted": 5, "modified": 8, "total": 33},
        }
        result = write_daily_churn_metrics("https://github.com/owner/repo", daily)

        assert result.success is True
        assert result.points_written == 2

    @patch("src.core.influx.get_client")
    def test_write_daily_churn_empty(self, mock_get_client):
        result = write_daily_churn_metrics("https://github.com/owner/repo", {})
        assert result.success is True
        assert result.points_written == 0


class TestTaigaWrites:
    """Taiga write functions should persist sprint and cycle-time points."""

    @patch("src.core.influx.get_client")
    def test_write_taiga_metrics_with_cycle_time(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        result = write_taiga_metrics(
            project_slug="proj",
            sprints_data=[
                {
                    "sprint_id": 10,
                    "sprint_name": "Sprint 1",
                    "adopted_work_count": 2,
                    "created_stories": 5,
                    "completed_stories": 4,
                }
            ],
            cycle_time_data=[
                {
                    "user_story_id": 101,
                    "user_story_name": "US-101",
                    "end_timestamp": "2026-03-28T12:00:00+00:00",
                    "cycle_time_hours": 36.0,
                }
            ],
        )

        assert result.success is True
        assert result.points_written == 2
        mock_write_api.write.assert_called_once()

        points = mock_write_api.write.call_args.kwargs["record"]
        lines = [p.to_line_protocol() for p in points]
        assert any("taiga_adopted_work" in line for line in lines)
        assert any("taiga_cycle_time" in line for line in lines)

    @patch("src.core.influx.get_client")
    def test_write_taiga_metrics_skips_none_cycle_time(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        result = write_taiga_metrics(
            project_slug="proj",
            sprints_data=[],
            cycle_time_data=[{"user_story_id": 202, "cycle_time_hours": None}],
        )

        assert result.success is False
        assert result.points_written == 0
        assert result.points_failed == 0
        assert "No valid points to write" in result.errors

class TestCycleTimeWrites:
    """Cycle time write functions should persist sprint and cycle-time points."""
    @patch("src.core.influx.get_client")
    def test_write_cycle_time_success(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        result = write_cycle_time_metrics(
            project_slug="proj",
            story_cycle_times=[
                {"story_id": 1, "cycle_time_hours": 24.0},
                {"story_id": 2, "cycle_time_hours": 48.0}],
        )
        
        assert isinstance(result, WriteResult)
        assert result.success is True
        assert result.points_written > 0

# =========================================================================
# 6. Error recovery tests
# =========================================================================

class TestErrorRecovery:
    """Verify that pipeline errors don't crash the worker and are reported properly."""

    @patch("src.core.influx.get_client")
    def test_retry_uses_exponential_backoff(self, mock_get_client):
        """Verify that successive retries wait progressively longer."""
        mock_write_api = MagicMock()
        mock_write_api.write.side_effect = Exception("unavailable")
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        sleep_calls = []
        original_sleep = time.sleep

        def tracking_sleep(secs):
            sleep_calls.append(secs)
            # don't actually sleep

        with patch("src.core.influx.time.sleep", side_effect=tracking_sleep):
            result = _write_with_retry([_build_loc_point(_sample_loc_metric())])

        assert result.success is False
        # should have MAX_RETRIES sleep calls with increasing durations
        assert len(sleep_calls) == MAX_RETRIES
        for i in range(1, len(sleep_calls)):
            assert sleep_calls[i] > sleep_calls[i - 1]

    @patch("src.core.influx.get_client")
    def test_error_messages_are_descriptive(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_write_api.write.side_effect = ConnectionError("ECONNREFUSED")
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        with patch("src.core.influx.RETRY_BACKOFF_BASE", 0.01):
            result = write_loc_metric(_sample_loc_metric())

        assert result.success is False
        for err in result.errors:
            assert "ECONNREFUSED" in err
            assert "attempt" in err

    @patch("src.core.influx.get_client")
    def test_write_result_tracks_all_error_attempts(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_write_api.write.side_effect = Exception("fail")
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        with patch("src.core.influx.RETRY_BACKOFF_BASE", 0.01):
            result = write_loc_metric(_sample_loc_metric())

        # should log each attempt
        assert len(result.errors) == MAX_RETRIES + 1
        for i, err in enumerate(result.errors):
            assert f"attempt {i + 1}" in err


# =========================================================================
# 7. Performance benchmarking (1000+ data points)
# =========================================================================

class TestPerformanceBenchmark:
    """Benchmark: write 1000+ points and verify throughput and correctness."""

    @patch("src.core.influx.get_client")
    def test_write_1000_points_in_batch(self, mock_get_client):
        """Write 1000+ LOC metric points in a single batch call and measure time."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        count = 1200
        metrics = [
            _sample_loc_metric(
                file_path=f"src/pkg{i // 100}/file_{i}.py",
                total_loc=i * 10,
                code_loc=i * 8,
                comment_loc=i,
                blank_loc=i,
            )
            for i in range(count)
        ]

        start = time.time()
        result = batch_write_loc_metrics(metrics)
        elapsed = time.time() - start

        assert result.success is True
        assert result.points_written == count
        assert result.points_failed == 0
        # should be written in ceil(1200/500) = 3 chunks
        assert mock_write_api.write.call_count == 3

        # basic throughput check: building + writing 1200 points should be fast
        assert elapsed < 5.0, f"Batch write of {count} points took {elapsed:.2f}s (too slow)"

    @patch("src.core.influx.get_client")
    def test_write_2000_points_still_succeeds(self, mock_get_client):
        """Stress test: 2000 points should not fail or run out of memory."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        count = 2000
        metrics = [_sample_loc_metric(file_path=f"f_{i}.py", total_loc=i) for i in range(count)]

        result = batch_write_loc_metrics(metrics)

        assert result.success is True
        assert result.points_written == count
        # ceil(2000/500) = 4 batches
        assert mock_write_api.write.call_count == 4

    @patch("src.core.influx.get_client")
    def test_batch_write_throughput_per_second(self, mock_get_client):
        """Measure and assert a minimum throughput of 1000 points/second."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        count = 1000
        metrics = [_sample_loc_metric(file_path=f"f_{i}.py") for i in range(count)]

        start = time.time()
        result = batch_write_loc_metrics(metrics)
        elapsed = time.time() - start

        throughput = count / elapsed if elapsed > 0 else float("inf")
        assert result.success is True
        assert throughput > 1000, f"Throughput {throughput:.0f} pts/s is below 1000 pts/s minimum"


# =========================================================================
# 8. Worker → InfluxDB integration (pool uses batch_write_loc_metrics)
# =========================================================================

class TestWorkerPipelineIntegration:
    """Verify that the worker pool calls the batch pipeline correctly."""

    @patch("src.core.influx.batch_write_loc_metrics")
    @patch("src.worker.pool.GitRepoCloner")
    def test_pool_calls_batch_write(self, mock_cloner_cls, mock_batch_write):
        """_run_job should call batch_write_loc_metrics instead of individual writes."""
        import tempfile, shutil, os
        from src.worker.pool import WorkerPool

        tmp = tempfile.mkdtemp(prefix="test_pipeline_")
        os.makedirs(tmp, exist_ok=True)
        with open(os.path.join(tmp, "app.py"), "w") as f:
            f.write("print('hello')\n")

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner_cls.return_value = mock_cloner

        # make batch_write return a successful WriteResult
        mock_batch_write.return_value = WriteResult(success=True, points_written=3)

        pool = WorkerPool(pool_size=1)
        pool.start()
        try:
            record = pool.submit("job-pipe", repo_url="https://github.com/owner/repo")
            record.future.result(timeout=10)

            assert record.status == "completed"
            mock_batch_write.assert_called_once()
            # should have passed a list of metric dicts
            call_args = mock_batch_write.call_args[0][0]
            assert isinstance(call_args, list)
            assert len(call_args) >= 1  # at least project-level metric
        finally:
            pool.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.core.influx.batch_write_loc_metrics")
    @patch("src.worker.pool.GitRepoCloner")
    def test_pool_handles_batch_failure_gracefully(self, mock_cloner_cls, mock_batch_write):
        """If batch_write raises, the job should still complete (best-effort writes)."""
        import tempfile, shutil, os
        from src.worker.pool import WorkerPool

        tmp = tempfile.mkdtemp(prefix="test_pipe_fail_")
        os.makedirs(tmp, exist_ok=True)
        with open(os.path.join(tmp, "app.py"), "w") as f:
            f.write("x = 1\n")

        mock_cloner = MagicMock()
        mock_cloner.clone.return_value = tmp
        mock_cloner_cls.return_value = mock_cloner

        mock_batch_write.side_effect = Exception("InfluxDB unreachable")

        pool = WorkerPool(pool_size=1)
        pool.start()
        try:
            record = pool.submit("job-fail-pipe", repo_url="https://github.com/owner/repo")
            record.future.result(timeout=10)

            # job should still complete — influx failure is non-fatal
            assert record.status == "completed"
            assert record.result is not None
            assert record.result["total_loc"] >= 1
        finally:
            pool.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)
