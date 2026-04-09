"""Tests for timeseries and code-quality routes in src/api/routes.py."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


# ── Timeseries snapshot endpoints ──────────────────────────────────────────


@patch("src.api.routes.query_latest_snapshot")
def test_latest_snapshot_returns_data(mock_query):
    mock_query.return_value = {
        "time": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "repo_id": "r1",
        "repo_name": "repo",
        "commit_hash": "abc",
        "branch": "main",
        "granularity": "project",
    }
    resp = client.get("/metrics/timeseries/snapshots/r1/latest")
    assert resp.status_code == 200
    assert resp.json()["repo_id"] == "r1"


@patch("src.api.routes.query_latest_snapshot")
def test_latest_snapshot_empty(mock_query):
    mock_query.return_value = None
    resp = client.get("/metrics/timeseries/snapshots/r1/latest")
    assert resp.status_code == 200
    assert resp.json()["latest_snapshot"] is None


def test_latest_snapshot_invalid_granularity():
    resp = client.get("/metrics/timeseries/snapshots/r1/latest?granularity=bad")
    assert resp.status_code == 400


@patch("src.api.routes.query_timeseries_snapshots_by_repo")
def test_snapshot_range(mock_query):
    mock_query.return_value = [
        {
            "time": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "repo_id": "r1", "repo_name": "repo", "commit_hash": "a",
            "branch": "main", "granularity": "project",
        }
    ]
    resp = client.get(
        "/metrics/timeseries/snapshots/r1/range",
        params={"start_time": "2026-01-01T00:00:00Z", "end_time": "2026-02-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_snapshot_range_invalid_times():
    resp = client.get(
        "/metrics/timeseries/snapshots/r1/range",
        params={"start_time": "2026-02-01T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"},
    )
    assert resp.status_code == 400


@patch("src.api.routes.query_snapshot_at_timestamp")
def test_snapshot_at_time(mock_query):
    mock_query.return_value = {
        "time": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "repo_id": "r1", "repo_name": "repo", "commit_hash": "a",
        "branch": "main", "granularity": "project",
    }
    resp = client.get("/metrics/timeseries/snapshots/r1/at/2026-01-01T00:00:00Z")
    assert resp.status_code == 200


@patch("src.api.routes.query_snapshot_at_timestamp")
def test_snapshot_at_time_not_found(mock_query):
    mock_query.return_value = None
    resp = client.get("/metrics/timeseries/snapshots/r1/at/2026-01-01T00:00:00Z")
    assert resp.status_code == 404


@patch("src.api.routes.query_snapshots_by_commit")
def test_snapshots_by_commit(mock_query):
    mock_query.return_value = [
        {
            "time": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "repo_id": "r1", "repo_name": "repo", "commit_hash": "abc123",
            "branch": "main", "granularity": "project",
        }
    ]
    resp = client.get("/metrics/timeseries/snapshots/r1/commit/abc123")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


@patch("src.api.routes.query_commits_in_range")
def test_commits_in_range(mock_query):
    mock_query.return_value = [
        {"commit_hash": "abc", "branch": "main", "time": datetime(2026, 1, 15, tzinfo=timezone.utc)}
    ]
    resp = client.get(
        "/metrics/timeseries/commits/r1",
        params={"start_time": "2026-01-01T00:00:00Z", "end_time": "2026-02-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_commits_in_range_invalid_times():
    resp = client.get(
        "/metrics/timeseries/commits/r1",
        params={"start_time": "bad", "end_time": "bad"},
    )
    assert resp.status_code == 400


@patch("src.api.routes.query_compare_commits")
def test_compare_commits(mock_query):
    mock_query.return_value = {
        "repo_id": "r1", "commit1": "a", "commit2": "b",
        "granularity": "project", "snapshots_commit1": [], "snapshots_commit2": [],
    }
    resp = client.get(
        "/metrics/timeseries/commits/r1/compare",
        params={"commit1": "a", "commit2": "b"},
    )
    assert resp.status_code == 200


def test_compare_commits_bad_granularity():
    resp = client.get(
        "/metrics/timeseries/commits/r1/compare",
        params={"commit1": "a", "commit2": "b", "granularity": "bad"},
    )
    assert resp.status_code == 400


@patch("src.api.routes.query_loc_trend")
def test_loc_trend(mock_query):
    mock_query.return_value = [
        {"time": datetime(2026, 1, 1, tzinfo=timezone.utc), "total_loc": 100}
    ]
    resp = client.get(
        "/metrics/timeseries/trend/r1",
        params={"start_time": "2026-01-01T00:00:00Z", "end_time": "2026-02-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_loc_trend_invalid_times():
    resp = client.get(
        "/metrics/timeseries/trend/r1",
        params={"start_time": "bad", "end_time": "bad"},
    )
    assert resp.status_code == 400


@patch("src.api.routes.query_current_loc_by_branch")
def test_branch_metrics(mock_query):
    mock_query.return_value = [
        {"branch": "main", "total_loc": 500, "time": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    ]
    resp = client.get("/metrics/timeseries/by-branch/r1")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


@patch("src.api.routes.query_loc_change_between")
def test_loc_change(mock_query):
    mock_query.return_value = {
        "repo_id": "r1", "granularity": "project",
        "timestamp1": "2026-01-01", "timestamp2": "2026-02-01",
        "loc_at_time1": 1000, "loc_at_time2": 1050,
        "absolute_change": 50, "percent_change": 5.0,
    }
    resp = client.get(
        "/metrics/timeseries/change/r1",
        params={"timestamp1": "2026-01-01T00:00:00Z", "timestamp2": "2026-02-01T00:00:00Z"},
    )
    assert resp.status_code == 200


def test_loc_change_invalid_timestamps():
    resp = client.get(
        "/metrics/timeseries/change/r1",
        params={"timestamp1": "bad", "timestamp2": "bad"},
    )
    assert resp.status_code == 400


def test_loc_change_bad_granularity():
    resp = client.get(
        "/metrics/timeseries/change/r1",
        params={
            "timestamp1": "2026-01-01T00:00:00Z",
            "timestamp2": "2026-02-01T00:00:00Z",
            "granularity": "bad",
        },
    )
    assert resp.status_code == 400


# ── Code quality metric endpoints (validation only, no git clone) ──────────


def test_fog_index_missing_params():
    resp = client.post("/metrics/fog-index", json={"branch": "main"})
    assert resp.status_code == 400


def test_class_coverage_missing_params():
    resp = client.post("/metrics/class-coverage", json={"branch": "main"})
    assert resp.status_code == 400


def test_method_coverage_missing_params():
    resp = client.post("/metrics/method-coverage", json={"branch": "main"})
    assert resp.status_code == 400


def test_taiga_metrics_missing_params():
    resp = client.post("/metrics/taiga-metrics", json={})
    assert resp.status_code == 400


# ── Cycle time endpoint ───────────────────────────────────────────────────


def test_cycle_time_bad_date_format():
    resp = client.get("/cycle-time", params={"start": "bad", "end": "bad", "slug": "proj"})
    assert resp.status_code == 400


def test_cycle_time_start_after_end():
    resp = client.get("/cycle-time", params={"start": "2026-02-01", "end": "2026-01-01", "slug": "proj"})
    assert resp.status_code == 400


def test_cycle_time_missing_slug():
    resp = client.get("/cycle-time", params={"start": "2026-01-01", "end": "2026-02-01"})
    assert resp.status_code == 400
