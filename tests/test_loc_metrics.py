from src.api.models import LOCMetrics
from pydantic import ValidationError
import pytest

def test_loc_metrics_valid():
    metrics = LOCMetrics(
        repo_id="123",
        repo_name="example-repo",
        branch="main",
        commit_hash="abc123",
        language="Python",
        granularity="project",
        total_loc=1000,
        code_loc=800,
        comment_loc=150,
        blank_loc=50,
        collected_at="2026-02-12T12:00:00Z"
    )
    assert metrics.repo_id == "123"
    assert metrics.total_loc == 1000
    assert metrics.code_loc == 800
    assert metrics.comment_loc == 150
    assert metrics.blank_loc == 50
    assert metrics.collected_at == "2026-02-12T12:00:00Z"

def test_loc_metrics_invalid_missing_field():
    with pytest.raises(ValidationError):
        LOCMetrics(
            repo_id="123",
            repo_name="example-repo",
            branch="main",
            commit_hash="abc123",
            language="Python",
            granularity="project",
            total_loc=1000,
            code_loc=800,
            comment_loc=150,
            blank_loc=50
            # collected_at missing
        )
