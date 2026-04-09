"""Tests for InfluxDB write helper functions in src/core/influx.py."""
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.core.influx import (
    write_fog_index_metrics,
    write_class_coverage_metrics,
    write_method_coverage_metrics,
    write_taiga_metrics,
    write_wip_metrics,
    map_wip_response_to_points,
)


def _mock_client():
    mock_client = MagicMock()
    mock_write_api = MagicMock()
    mock_client.write_api.return_value = mock_write_api
    return mock_client


@patch("src.core.influx.get_client")
def test_write_fog_index_metrics(mock_gc):
    mock_gc.return_value = _mock_client()
    results = [
        (8.5, "OK", "comment", "src/foo.py", ""),
        (None, "NO_COMMENTS", "comment", "src/bar.py", "No comment text found."),
    ]
    result = write_fog_index_metrics("repo", "main", results)
    assert result.success


@patch("src.core.influx.get_client")
def test_write_fog_index_empty(mock_gc):
    result = write_fog_index_metrics("repo", "main", [])
    assert not result.success


@patch("src.core.influx.get_client")
def test_write_class_coverage(mock_gc):
    mock_gc.return_value = _mock_client()
    result = write_class_coverage_metrics(
        repo_name="repo", branch="main",
        total_classes=10, documented_classes=8, coverage_percent=80.0,
        commit_sha="abc123",
        files_detail=[{"file_path": "A.java", "total_classes": 5, "documented_classes": 4, "coverage_percent": 80.0}],
    )
    assert result.success


@patch("src.core.influx.get_client")
def test_write_class_coverage_no_files(mock_gc):
    mock_gc.return_value = _mock_client()
    result = write_class_coverage_metrics(
        repo_name="repo", branch="main",
        total_classes=0, documented_classes=0, coverage_percent=0.0,
    )
    assert result.success


@patch("src.core.influx.get_client")
def test_write_method_coverage(mock_gc):
    mock_gc.return_value = _mock_client()
    result = write_method_coverage_metrics(
        repo_name="repo", branch="main",
        public_coverage=90.0, protected_coverage=80.0,
        package_coverage=70.0, private_coverage=60.0,
        commit_sha="abc",
    )
    assert result.success


@patch("src.core.influx.get_client")
def test_write_taiga_metrics(mock_gc):
    mock_gc.return_value = _mock_client()
    sprints = [{"sprint_id": 1, "sprint_name": "Sprint 1", "adopted_work_count": 3, "created_stories": 5, "completed_stories": 4}]
    cycle_time = [
        {"user_story_id": 10, "user_story_name": "Story A", "cycle_time_hours": 48.0, "end_timestamp": "2026-01-15T00:00:00Z"},
        {"user_story_id": 11, "cycle_time_hours": None},
    ]
    result = write_taiga_metrics("proj-slug", sprints, cycle_time)
    assert result.success


@patch("src.core.influx.get_client")
def test_write_taiga_metrics_empty(mock_gc):
    result = write_taiga_metrics("proj-slug", [], [])
    assert not result.success


@patch("src.core.influx.get_client")
def test_write_wip_metrics(mock_gc):
    mock_gc.return_value = _mock_client()
    wip_resp = {
        "project_id": 1, "project_slug": "proj",
        "sprints": [{
            "sprint_id": 1, "sprint_name": "S1",
            "daily_wip": [
                {"date": "2026-01-01T00:00:00", "wip_count": 3, "backlog_count": 5, "done_count": 2},
                {"date": "2026-01-02T00:00:00", "wip_count": 4, "backlog_count": 4, "done_count": 3},
            ],
        }],
    }
    result = write_wip_metrics(wip_resp)
    assert result.success


def test_map_wip_empty_sprints():
    points = map_wip_response_to_points({"project_id": 1, "project_slug": "p", "sprints": []})
    assert points == []


def test_map_wip_no_daily():
    points = map_wip_response_to_points({
        "project_id": 1, "project_slug": "p",
        "sprints": [{"sprint_id": 1, "sprint_name": "S1", "daily_wip": []}],
    })
    assert points == []


def test_map_wip_missing_date():
    points = map_wip_response_to_points({
        "project_id": 1, "project_slug": "p",
        "sprints": [{"sprint_id": 1, "sprint_name": "S1", "daily_wip": [{"wip_count": 1}]}],
    })
    assert points == []
