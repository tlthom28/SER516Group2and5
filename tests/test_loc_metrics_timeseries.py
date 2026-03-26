from src.api.models import (
    LOCMetrics, TimeSeriesMetricSnapshot, SnapshotRecord, SnapshotData,
    CommitInfo, CommitListResponse, CommitComparisonResponse,
    LocTrendResponse, TrendPoint, BranchMetrics, BranchMetricsResponse, LocChangeResponse
)
from datetime import datetime
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_loc_metrics_time_series_query():
    # Create a list of LOCMetrics with different timestamps
    metrics_list = [
        LOCMetrics(
            repo_id="1",
            repo_name="repo1",
            branch="main",
            commit_hash="a1",
            language="Python",
            granularity="file",
            file_path="src/a.py",
            total_loc=100,
            code_loc=80,
            comment_loc=10,
            blank_loc=10,
            collected_at="2026-02-10T10:00:00Z"
        ),
        LOCMetrics(
            repo_id="1",
            repo_name="repo1",
            branch="main",
            commit_hash="a2",
            language="Python",
            granularity="file",
            file_path="src/a.py",
            total_loc=110,
            code_loc=90,
            comment_loc=10,
            blank_loc=10,
            collected_at="2026-02-12T10:00:00Z"
        ),
        LOCMetrics(
            repo_id="1",
            repo_name="repo1",
            branch="main",
            commit_hash="a3",
            language="Python",
            granularity="file",
            file_path="src/a.py",
            total_loc=120,
            code_loc=100,
            comment_loc=10,
            blank_loc=10,
            collected_at="2026-02-14T10:00:00Z"
        ),
    ]

    cutoff = datetime.fromisoformat("2026-02-11T00:00:00+00:00")
    filtered = [m for m in metrics_list if datetime.fromisoformat(m.collected_at.replace('Z', '+00:00')) > cutoff]

    assert len(filtered) == 2
    assert filtered[0].commit_hash == "a2"
    assert filtered[1].commit_hash == "a3"


def test_snapshot_record_creation():
    snapshot = SnapshotRecord(
        timestamp="2026-02-25T19:00:00+00:00",
        repo_id="test-repo",
        repo_name="test-repo",
        commit_hash="abc123def456",
        branch="main",
        granularity="project",
        metrics=SnapshotData(
            total_loc=500,
            code_loc=400,
            comment_loc=50,
            blank_loc=50
        )
    )
    assert snapshot.repo_id == "test-repo"
    assert snapshot.commit_hash == "abc123def456"
    assert snapshot.metrics.total_loc == 500
    assert snapshot.granularity == "project"


def test_timeseries_metric_snapshot_model():
    snapshot = TimeSeriesMetricSnapshot(
        repo_id="my-repo",
        repo_name="my-repo",
        commit_hash="xyz789",
        commit_timestamp="2026-02-25T18:00:00Z",
        branch="main",
        snapshot_timestamp="2026-02-25T19:00:00Z",
        granularity="project",
        total_loc=1000,
        code_loc=800,
        comment_loc=100,
        blank_loc=100,
        project_name="my-project"
    )
    assert snapshot.repo_id == "my-repo"
    assert snapshot.commit_hash == "xyz789"
    assert snapshot.total_loc == 1000


@patch("src.api.routes.query_latest_snapshot")
def test_get_latest_snapshot_endpoint(mock_query):
    mock_query.return_value = {
        "time": datetime.fromisoformat("2026-02-25T19:00:00+00:00"),
        "repo_id": "test-repo",
        "repo_name": "test-repo",
        "commit_hash": "abc123",
        "branch": "main",
        "granularity": "project",
        "file_path": None,
        "package_name": None
    }
    
    response = client.get("/metrics/timeseries/snapshots/test-repo/latest?granularity=project")
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["latest_snapshot"] is not None


@patch("src.api.routes.query_timeseries_snapshots_by_repo")
def test_get_snapshot_history_endpoint(mock_query):
    mock_query.return_value = [
        {
            "time": datetime.fromisoformat("2026-02-20T10:00:00+00:00"),
            "repo_id": "test-repo",
            "repo_name": "test-repo",
            "commit_hash": "hash1",
            "branch": "main",
            "granularity": "project",
            "file_path": None,
            "package_name": None
        },
        {
            "time": datetime.fromisoformat("2026-02-25T19:00:00+00:00"),
            "repo_id": "test-repo",
            "repo_name": "test-repo",
            "commit_hash": "hash2",
            "branch": "main",
            "granularity": "project",
            "file_path": None,
            "package_name": None
        }
    ]
    
    response = client.get(
        "/metrics/timeseries/snapshots/test-repo/range?"
        "start_time=2026-02-20T00:00:00Z&end_time=2026-02-26T00:00:00Z&granularity=project"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["count"] == 2


@patch("src.api.routes.query_snapshot_at_timestamp")
def test_get_snapshot_at_time_endpoint(mock_query):
    mock_query.return_value = {
        "time": datetime.fromisoformat("2026-02-25T19:00:00+00:00"),
        "repo_id": "test-repo",
        "repo_name": "test-repo",
        "commit_hash": "abc123",
        "branch": "main",
        "granularity": "project",
        "file_path": None,
        "package_name": None
    }
    
    response = client.get("/metrics/timeseries/snapshots/test-repo/at/2026-02-25T19:00:00Z")
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["commit_hash"] == "abc123"


@patch("src.api.routes.query_snapshots_by_commit")
def test_get_snapshots_for_commit_endpoint(mock_query):
    mock_query.return_value = [
        {
            "time": datetime.fromisoformat("2026-02-25T19:00:00+00:00"),
            "repo_id": "test-repo",
            "repo_name": "test-repo",
            "commit_hash": "abc123",
            "branch": "main",
            "granularity": "project",
            "file_path": None,
            "package_name": None
        },
        {
            "time": datetime.fromisoformat("2026-02-25T19:00:00+00:00"),
            "repo_id": "test-repo",
            "repo_name": "test-repo",
            "commit_hash": "abc123",
            "branch": "main",
            "granularity": "file",
            "file_path": "src/main.py",
            "package_name": None
        }
    ]
    
    response = client.get("/metrics/timeseries/snapshots/test-repo/commit/abc123")
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["commit_hash"] == "abc123"
    assert data["count"] == 2


@patch("src.api.routes.query_commits_in_range")
def test_get_commits_in_range_endpoint(mock_query):
    mock_query.return_value = [
        {
            "commit_hash": "hash1",
            "repo_id": "test-repo",
            "branch": "main",
            "time": datetime.fromisoformat("2026-02-20T10:00:00+00:00"),
        },
        {
            "commit_hash": "hash2",
            "repo_id": "test-repo",
            "branch": "develop",
            "time": datetime.fromisoformat("2026-02-25T19:00:00+00:00"),
        }
    ]
    
    response = client.get(
        "/metrics/timeseries/commits/test-repo?"
        "start_time=2026-02-20T00:00:00Z&end_time=2026-02-26T00:00:00Z&branch=main"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["count"] == 2
    assert data["commits"][0]["commit_hash"] == "hash1"


@patch("src.api.routes.query_compare_commits")
def test_compare_commits_endpoint(mock_query):
    mock_query.return_value = {
        "repo_id": "test-repo",
        "commit1": "hash1",
        "commit2": "hash2",
        "granularity": "project",
        "snapshots_commit1": [{"value": 100}],
        "snapshots_commit2": [{"value": 120}],
    }
    
    response = client.get(
        "/metrics/timeseries/commits/test-repo/compare?"
        "commit1=hash1&commit2=hash2&granularity=project"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["commit1"] == "hash1"
    assert data["commit2"] == "hash2"
    assert data["granularity"] == "project"


@patch("src.api.routes.query_loc_trend")
def test_get_loc_trend_endpoint(mock_query):
    mock_query.return_value = [
        {
            "time": datetime.fromisoformat("2026-02-20T10:00:00+00:00"),
            "repo_id": "test-repo",
            "total_loc": 1000,
            "granularity": "project",
        },
        {
            "time": datetime.fromisoformat("2026-02-25T19:00:00+00:00"),
            "repo_id": "test-repo",
            "total_loc": 1200,
            "granularity": "project",
        }
    ]
    
    response = client.get(
        "/metrics/timeseries/trend/test-repo?"
        "start_time=2026-02-20T00:00:00Z&end_time=2026-02-26T00:00:00Z&granularity=project"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["granularity"] == "project"
    assert data["count"] == 2
    assert data["trend"][0]["total_loc"] == 1000


@patch("src.api.routes.query_current_loc_by_branch")
def test_get_branch_metrics_endpoint(mock_query):
    mock_query.return_value = [
        {
            "branch": "main",
            "time": datetime.fromisoformat("2026-02-25T19:00:00+00:00"),
            "total_loc": 1500,
            "repo_id": "test-repo",
        },
        {
            "branch": "develop",
            "time": datetime.fromisoformat("2026-02-25T18:00:00+00:00"),
            "total_loc": 1400,
            "repo_id": "test-repo",
        }
    ]
    
    response = client.get("/metrics/timeseries/by-branch/test-repo")
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["count"] == 2
    assert data["branches"][0]["branch"] == "main"
    assert data["branches"][0]["total_loc"] == 1500


@patch("src.api.routes.query_loc_change_between")
def test_get_loc_change_endpoint(mock_query):
    mock_query.return_value = {
        "repo_id": "test-repo",
        "timestamp1": "2026-02-20T10:00:00+00:00",
        "timestamp2": "2026-02-25T19:00:00+00:00",
        "loc_at_time1": 1000,
        "loc_at_time2": 1200,
        "absolute_change": 200,
        "percent_change": 20.0,
        "granularity": "project",
    }
    
    response = client.get(
        "/metrics/timeseries/change/test-repo?"
        "timestamp1=2026-02-20T10:00:00Z&timestamp2=2026-02-25T19:00:00Z&granularity=project"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "test-repo"
    assert data["loc_at_time1"] == 1000
    assert data["loc_at_time2"] == 1200
    assert data["absolute_change"] == 200
    assert data["percent_change"] == 20.0


def test_commit_info_model():
    commit = CommitInfo(
        commit_hash="abc123",
        branch="main",
        time="2026-02-25T19:00:00+00:00"
    )
    assert commit.commit_hash == "abc123"
    assert commit.branch == "main"
    assert commit.time == "2026-02-25T19:00:00+00:00"


def test_commit_list_response_model():
    commits = [
        CommitInfo(commit_hash="hash1", branch="main", time="2026-02-20T10:00:00+00:00"),
        CommitInfo(commit_hash="hash2", branch="develop", time="2026-02-25T19:00:00+00:00"),
    ]
    response = CommitListResponse(
        repo_id="test-repo",
        start_time="2026-02-20T00:00:00+00:00",
        end_time="2026-02-26T00:00:00+00:00",
        branch=None,
        commits=commits,
        count=2
    )
    assert response.repo_id == "test-repo"
    assert len(response.commits) == 2
    assert response.count == 2


def test_trend_point_model():
    point = TrendPoint(
        time="2026-02-25T19:00:00+00:00",
        total_loc=1500
    )
    assert point.time == "2026-02-25T19:00:00+00:00"
    assert point.total_loc == 1500


def test_loc_trend_response_model():
    trend = [
        TrendPoint(time="2026-02-20T10:00:00+00:00", total_loc=1000),
        TrendPoint(time="2026-02-25T19:00:00+00:00", total_loc=1200),
    ]
    response = LocTrendResponse(
        repo_id="test-repo",
        granularity="project",
        start_time="2026-02-20T00:00:00+00:00",
        end_time="2026-02-26T00:00:00+00:00",
        trend=trend,
        count=2
    )
    assert response.repo_id == "test-repo"
    assert response.granularity == "project"
    assert len(response.trend) == 2


def test_branch_metrics_model():
    metrics = BranchMetrics(
        branch="main",
        total_loc=1500,
        updated_at="2026-02-25T19:00:00+00:00"
    )
    assert metrics.branch == "main"
    assert metrics.total_loc == 1500


def test_branch_metrics_response_model():
    branches = [
        BranchMetrics(branch="main", total_loc=1500, updated_at="2026-02-25T19:00:00+00:00"),
        BranchMetrics(branch="develop", total_loc=1400, updated_at="2026-02-25T18:00:00+00:00"),
    ]
    response = BranchMetricsResponse(
        repo_id="test-repo",
        branches=branches,
        count=2
    )
    assert response.repo_id == "test-repo"
    assert len(response.branches) == 2


def test_loc_change_response_model():
    response = LocChangeResponse(
        repo_id="test-repo",
        timestamp1="2026-02-20T10:00:00+00:00",
        timestamp2="2026-02-25T19:00:00+00:00",
        loc_at_time1=1000,
        loc_at_time2=1200,
        absolute_change=200,
        percent_change=20.0,
        granularity="project"
    )
    assert response.repo_id == "test-repo"
    assert response.loc_at_time1 == 1000
    assert response.loc_at_time2 == 1200
    assert response.absolute_change == 200
    assert response.percent_change == 20.0


def test_commit_comparison_response_model():
    response = CommitComparisonResponse(
        repo_id="test-repo",
        commit1="hash1",
        commit2="hash2",
        granularity="project",
        snapshots_commit1=[{"value": 100}],
        snapshots_commit2=[{"value": 120}]
    )
    assert response.repo_id == "test-repo"
    assert response.commit1 == "hash1"
    assert response.commit2 == "hash2"
    assert len(response.snapshots_commit1) == 1
    assert len(response.snapshots_commit2) == 1
