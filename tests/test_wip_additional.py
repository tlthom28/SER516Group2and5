"""
Additional basic tests for WIP module to enhance coverage.
These tests focus on integration scenarios and edge cases.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, date
import requests
from src.metrics.wip import (
    TaigaFetchError,
    DailyWIPMetric,
    WIPMetric,
    _validate_taiga_url,
    _build_status_name_to_id,
    _categorize_status,
    _extract_status_at_date,
    calculate_daily_wip,
    calculate_kanban_wip,
)


class TestBasicWIPFunctionality:
    """Basic tests to understand core WIP functionality."""

    def test_daily_wip_metric_creation(self):
        """Test creating a basic daily WIP metric."""
        metric = DailyWIPMetric(
            date="2024-01-01",
            wip_count=5,
            backlog_count=10,
            done_count=3
        )
        
        assert metric.date == "2024-01-01"
        assert metric.wip_count == 5
        assert metric.backlog_count == 10
        assert metric.done_count == 3

    def test_wip_metric_with_empty_daily_list(self):
        """Test WIP metric with no daily data."""
        metric = WIPMetric(
            project_id=123,
            project_slug="test-project",
            sprint_id=1,
            daily_wip=[]
        )
        
        assert metric.project_id == 123
        assert len(metric.daily_wip) == 0

    def test_wip_metric_with_multiple_days(self):
        """Test WIP metric with multiple days of data."""
        daily_metrics = [
            DailyWIPMetric("2024-01-01", 5, 10, 0),
            DailyWIPMetric("2024-01-02", 4, 9, 1),
            DailyWIPMetric("2024-01-03", 3, 8, 2),
        ]
        
        metric = WIPMetric(
            project_id=123,
            project_slug="test-project",
            sprint_id=1,
            daily_wip=daily_metrics
        )
        
        assert len(metric.daily_wip) == 3
        assert metric.daily_wip[0].wip_count == 5
        assert metric.daily_wip[2].done_count == 2


class TestURLValidation:
    """Basic tests for URL validation."""

    def test_standard_taiga_url(self):
        """Test parsing a standard Taiga project URL."""
        url = "https://taiga.io/project/my-awesome-project"
        slug = _validate_taiga_url(url)
        assert slug == "my-awesome-project"

    def test_url_with_trailing_slash(self):
        """Test URL with trailing slash is handled correctly."""
        url = "https://taiga.io/project/my-project/"
        slug = _validate_taiga_url(url)
        assert slug == "my-project"

    def test_url_with_kanban_view(self):
        """Test URL pointing to kanban view."""
        url = "https://tree.taiga.io/project/team-project/kanban"
        slug = _validate_taiga_url(url)
        assert slug == "team-project"

    def test_empty_url_raises_error(self):
        """Test that empty URL raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_taiga_url("")

    def test_invalid_url_format_raises_error(self):
        """Test that invalid URL format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid Taiga URL"):
            _validate_taiga_url("https://taiga.io/some/other/path")


class TestStatusCategorization:
    """Basic tests for status categorization logic."""

    def test_none_status_is_backlog(self):
        """Test that None status is categorized as backlog."""
        status_map = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        
        category = _categorize_status(None, status_map)
        assert category == "backlog"

    def test_closed_status_is_done(self):
        """Test that closed status is categorized as done."""
        status_map = {
            1: {"name": "New", "is_closed": False, "order": 1},
            3: {"name": "Done", "is_closed": True, "order": 3},
        }
        
        category = _categorize_status(3, status_map)
        assert category == "done"

    def test_first_status_is_backlog(self):
        """Test that the first status (lowest order) is backlog."""
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
            3: {"name": "Review", "is_closed": False, "order": 3},
        }
        
        category = _categorize_status(1, status_map, min_order=1)
        assert category == "backlog"

    def test_middle_status_is_wip(self):
        """Test that middle statuses are categorized as WIP."""
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
            3: {"name": "Review", "is_closed": False, "order": 3},
        }
        
        category = _categorize_status(2, status_map, min_order=1)
        assert category == "wip"

    def test_status_by_name_string(self):
        """Test categorizing status by name (string)."""
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
            3: {"name": "Done", "is_closed": True, "order": 3},
        }
        
        # Test by name
        category = _categorize_status("Done", status_map, min_order=1)
        assert category == "done"
        
        category = _categorize_status("In Progress", status_map, min_order=1)
        assert category == "wip"


class TestStatusNameMapping:
    """Basic tests for status name to ID mapping."""

    def test_build_status_name_to_id(self):
        """Test building reverse lookup from status name to ID."""
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
            3: {"name": "Done", "is_closed": True, "order": 3},
        }
        
        name_to_id = _build_status_name_to_id(status_map)
        
        assert name_to_id["Backlog"] == 1
        assert name_to_id["In Progress"] == 2
        assert name_to_id["Done"] == 3

    def test_build_status_name_to_id_skips_empty_names(self):
        """Test that empty status names are skipped."""
        status_map = {
            1: {"name": "Backlog", "is_closed": False},
            2: {"name": "", "is_closed": False},
            3: {},  # No name key
        }
        
        name_to_id = _build_status_name_to_id(status_map)
        
        assert "Backlog" in name_to_id
        assert "" not in name_to_id
        assert len(name_to_id) == 1


class TestStatusExtraction:
    """Basic tests for extracting status from history."""

    def test_extract_status_with_no_history(self):
        """Test extracting status when there's no history."""
        result = _extract_status_at_date([], date(2024, 1, 1))
        assert result is None

    def test_extract_status_before_any_changes(self):
        """Test status extraction before any status changes occurred."""
        history = [
            {
                "created_at": "2024-01-05T10:00:00Z",
                "values_diff": {"status": ["New", "In Progress"]},
            }
        ]
        
        # Query for date before the change
        result = _extract_status_at_date(history, date(2024, 1, 1))
        assert result is None

    def test_extract_status_after_change(self):
        """Test status extraction after a status change."""
        status_map = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        name_to_id = _build_status_name_to_id(status_map)
        
        history = [
            {
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"status": ["New", "In Progress"]},
            }
        ]
        
        # Query for date after the change
        result = _extract_status_at_date(history, date(2024, 1, 2), name_to_id)
        assert result == 2  # In Progress

    def test_extract_status_with_multiple_changes(self):
        """Test extracting status with multiple changes, should return latest."""
        status_map = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
            3: {"name": "Review", "is_closed": False, "order": 3},
        }
        name_to_id = _build_status_name_to_id(status_map)
        
        history = [
            {
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"status": ["New", "In Progress"]},
            },
            {
                "created_at": "2024-01-02T10:00:00Z",
                "values_diff": {"status": ["In Progress", "Review"]},
            },
        ]
        
        # Query for date after both changes
        result = _extract_status_at_date(history, date(2024, 1, 3), name_to_id)
        assert result == 3  # Review (latest status)


class TestIntegrationScenarios:
    """Integration tests for complete workflows."""

    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_simple_sprint_with_one_story(
        self,
        mock_validate,
        mock_project_id,
        mock_sprint_dates,
        mock_statuses,
        mock_stories,
        mock_history,
    ):
        """Test calculating WIP for a simple sprint with one story."""
        # Setup mocks
        mock_validate.return_value = "test-project"
        mock_project_id.return_value = 123
        mock_sprint_dates.return_value = (date(2024, 1, 1), date(2024, 1, 3))
        mock_statuses.return_value = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
            3: {"name": "Done", "is_closed": True, "order": 3},
        }
        mock_stories.return_value = [
            {"id": 1, "status": 2, "created_date": "2024-01-01T00:00:00Z"}
        ]
        mock_history.return_value = []
        
        # Calculate WIP
        metric = calculate_daily_wip("https://taiga.io/project/test-project", 1)
        
        # Assertions
        assert metric.project_id == 123
        assert metric.project_slug == "test-project"
        assert metric.sprint_id == 1
        assert len(metric.daily_wip) == 3  # 3 days
        
        # Story should be in WIP for all 3 days (status 2 = In Progress)
        assert metric.daily_wip[0].wip_count == 1
        assert metric.daily_wip[1].wip_count == 1
        assert metric.daily_wip[2].wip_count == 1

    @patch("src.metrics.wip._get_task_history")
    @patch("src.metrics.wip._get_tasks")
    @patch("src.metrics.wip._get_task_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_simple_kanban_with_one_task(
        self,
        mock_validate,
        mock_project_id,
        mock_task_statuses,
        mock_tasks,
        mock_task_history,
    ):
        """Test calculating WIP for a simple Kanban board with one task."""
        # Setup mocks
        mock_validate.return_value = "kanban-project"
        mock_project_id.return_value = 456
        mock_task_statuses.return_value = {
            1: {"name": "To Do", "is_closed": False, "order": 1},
            2: {"name": "Doing", "is_closed": False, "order": 2},
            3: {"name": "Done", "is_closed": True, "order": 3},
        }
        mock_tasks.return_value = [
            {"id": 10, "status": 2, "created_date": "2024-01-01T00:00:00Z"}
        ]
        mock_task_history.return_value = []
        
        # Calculate Kanban WIP for 2 days
        metric = calculate_kanban_wip(
            "https://taiga.io/project/kanban-project/kanban",
            recent_days=2
        )
        
        # Assertions
        assert metric.project_id == 456
        assert metric.project_slug == "kanban-project"
        assert metric.sprint_name == "kanban"
        assert len(metric.daily_wip) == 3  # today - 2 days to today = 3 days
        
        # Task should be in WIP (status 2 = Doing)
        assert all(day.wip_count == 1 for day in metric.daily_wip)


class TestErrorHandling:
    """Basic tests for error handling."""

    def test_taiga_fetch_error_creation(self):
        """Test creating TaigaFetchError exception."""
        error = TaigaFetchError("Test error message")
        assert str(error) == "Test error message"

    def test_taiga_fetch_error_can_be_raised(self):
        """Test that TaigaFetchError can be raised and caught."""
        with pytest.raises(TaigaFetchError) as exc_info:
            raise TaigaFetchError("Something went wrong")
        
        assert "Something went wrong" in str(exc_info.value)

    @patch("src.metrics.wip._validate_taiga_url")
    def test_calculate_daily_wip_with_invalid_url(self, mock_validate):
        """Test that invalid URL raises appropriate error."""
        mock_validate.side_effect = ValueError("Invalid URL format")
        
        with pytest.raises(ValueError, match="Invalid URL format"):
            calculate_daily_wip("invalid-url", 1)

    @patch("src.metrics.wip._validate_taiga_url")
    def test_calculate_kanban_wip_with_invalid_url(self, mock_validate):
        """Test that invalid Kanban URL raises appropriate error."""
        mock_validate.side_effect = ValueError("Invalid URL format")
        
        with pytest.raises(ValueError, match="Invalid URL format"):
            calculate_kanban_wip("invalid-url")


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_wip_metric_with_none_values(self):
        """Test WIP metric with None values for optional fields."""
        metric = WIPMetric()
        
        assert metric.project_id is None
        assert metric.project_slug is None
        assert metric.sprint_id is None
        assert metric.sprint_name is None
        assert metric.date_range_start is None
        assert metric.date_range_end is None
        assert metric.daily_wip == []

    def test_daily_wip_metric_with_zero_counts(self):
        """Test daily WIP metric with all zero counts."""
        metric = DailyWIPMetric(
            date="2024-01-01",
            wip_count=0,
            backlog_count=0,
            done_count=0
        )
        
        assert metric.wip_count == 0
        assert metric.backlog_count == 0
        assert metric.done_count == 0

    def test_status_extraction_with_malformed_history(self):
        """Test status extraction with malformed history entries."""
        history = [
            {"created_at": "invalid-date", "values_diff": {"status": ["A", "B"]}},
            {"created_at": "", "values_diff": {"status": ["C", "D"]}},
            {},  # Empty event
        ]
        
        result = _extract_status_at_date(history, date(2024, 1, 1))
        assert result is None

    def test_categorize_status_with_unknown_id(self):
        """Test categorizing an unknown status ID."""
        status_map = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "Done", "is_closed": True, "order": 2},
        }
        
        # Unknown status ID should be categorized as WIP
        category = _categorize_status(999, status_map)
        assert category == "wip"

    def test_categorize_status_with_unknown_name(self):
        """Test categorizing an unknown status name."""
        status_map = {
            1: {"name": "New", "is_closed": False, "order": 1},
        }
        
        # Unknown status name should be categorized as WIP
        category = _categorize_status("NonExistent", status_map, min_order=1)
        assert category == "wip"
