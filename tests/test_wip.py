import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, date
import requests
from src.metrics.wip import (
    TaigaFetchError,
    DailyWIPMetric,
    WIPMetric,
    _validate_taiga_url,
    _get_project_id,
    _get_project_statuses,
    _get_userstories,
    _get_userstory_history,
    _get_sprint_dates,
    _extract_status_at_date,
    _categorize_status,
    _build_status_name_to_id,
    _get_milestones,
    calculate_daily_wip,
    calculate_daily_wip_all_sprints,
    _get_task_statuses,
    _get_tasks,
    _get_task_history,
    calculate_kanban_wip,
)


class TestValidateTaigaUrl:
    def test_valid_url(self):
        url = "https://taiga.io/project/my-project"
        assert _validate_taiga_url(url) == "my-project"

    def test_valid_url_with_slash(self):
        url = "https://taiga.io/project/my-project/"
        assert _validate_taiga_url(url) == "my-project"

    def test_url_with_kanban_suffix(self):
        url = "https://tree.taiga.io/project/lesly-we-play-sport/kanban"
        assert _validate_taiga_url(url) == "lesly-we-play-sport"

    def test_url_with_backlog_suffix(self):
        url = "https://tree.taiga.io/project/my-project/backlog"
        assert _validate_taiga_url(url) == "my-project"

    def test_url_with_timeline_suffix(self):
        url = "https://tree.taiga.io/project/my-project/timeline"
        assert _validate_taiga_url(url) == "my-project"

    def test_empty_url(self):
        with pytest.raises(ValueError):
            _validate_taiga_url("")

    def test_invalid_url_format(self):
        url = "https://taiga.io/some/path"
        with pytest.raises(ValueError):
            _validate_taiga_url(url)


class TestGetProjectId:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"id": 123}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        assert _get_project_id("my-project") == 123

    @patch("src.metrics.wip.requests.get")
    def test_project_not_found(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError):
            _get_project_id("nonexistent")

    @patch("src.metrics.wip.requests.get")
    def test_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("Network error")

        with pytest.raises(TaigaFetchError):
            _get_project_id("my-project")

    @patch("src.metrics.wip.requests.get")
    def test_project_missing_id(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"name": "my-project"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError):
            _get_project_id("my-project")


class TestGetProjectStatuses:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "name": "Backlog", "is_closed": False, "order": 1},
            {"id": 2, "name": "Done", "is_closed": True, "order": 3},
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        statuses = _get_project_statuses(123)
        assert len(statuses) == 2
        assert statuses[1]["name"] == "Backlog"

    @patch("src.metrics.wip.requests.get")
    def test_empty_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError):
            _get_project_statuses(123)

    @patch("src.metrics.wip.requests.get")
    def test_unexpected_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = 123  # Not iterable
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError):
            _get_project_statuses(123)


class TestGetUserstories:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "title": "Story 1"},
            {"id": 2, "title": "Story 2"},
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        stories = _get_userstories(123)
        assert len(stories) == 2

    @patch("src.metrics.wip.requests.get")
    def test_empty_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        assert _get_userstories(123) == []

    @patch("src.metrics.wip.requests.get")
    def test_non_list_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"items": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        assert _get_userstories(123) == []


class TestGetUserstoryHistory:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                "id": 1,
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"status": [1, "Backlog", 2, "In Progress"]},
            }
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        history = _get_userstory_history(1)
        assert len(history) == 1

    @patch("src.metrics.wip.requests.get")
    def test_request_exception_returns_empty(self, mock_get):
        mock_get.side_effect = requests.RequestException("Not found")

        history = _get_userstory_history(1)
        assert history == []


class TestGetSprintDates:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {
            "id": 1,
            "estimated_start": "2024-01-01T00:00:00Z",
            "estimated_finish": "2024-01-14T00:00:00Z",
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        start, end = _get_sprint_dates(123, 1)
        assert start == date(2024, 1, 1)
        assert end == date(2024, 1, 14)

    @patch("src.metrics.wip.requests.get")
    def test_missing_dates(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"id": 1}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError):
            _get_sprint_dates(123, 1)


class TestExtractStatusAtDate:
    def setup_method(self):
        self.status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
            3: {"name": "Done", "is_closed": True, "order": 3},
        }
        self.name_to_id = _build_status_name_to_id(self.status_map)

    def test_status_before_any_event(self):
        target_date = date(2024, 1, 1)
        history = [
            {
                "created_at": "2024-01-02T10:00:00Z",
                "values_diff": {"status": ["New", "Backlog"]},
            }
        ]

        assert _extract_status_at_date(history, target_date, self.name_to_id) is None

    def test_status_after_event(self):
        target_date = date(2024, 1, 2)
        history = [
            {
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"status": ["Backlog", "In Progress"]},
            }
        ]

        assert _extract_status_at_date(history, target_date, self.name_to_id) == 2

    def test_multiple_events_returns_latest(self):
        target_date = date(2024, 1, 3)
        history = [
            {
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"status": ["New", "Backlog"]},
            },
            {
                "created_at": "2024-01-02T10:00:00Z",
                "values_diff": {"status": ["Backlog", "In Progress"]},
            },
            {
                "created_at": "2024-01-04T10:00:00Z",
                "values_diff": {"status": ["In Progress", "Done"]},
            },
        ]

        assert _extract_status_at_date(history, target_date, self.name_to_id) == 2

    def test_empty_history(self):
        assert _extract_status_at_date([], date(2024, 1, 1)) is None

    def test_no_status_changes(self):
        target_date = date(2024, 1, 1)
        history = [
            {
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"title": ["Old", "New"]},
            }
        ]

        assert _extract_status_at_date(history, target_date) is None

    def test_unknown_status_name_stored_as_string(self):
        target_date = date(2024, 1, 1)
        history = [
            {
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"status": ["New", "Unknown Status"]},
            }
        ]

        result = _extract_status_at_date(history, target_date, self.name_to_id)
        assert result == "Unknown Status"

    def test_single_element_status_ignored(self):
        target_date = date(2024, 1, 1)
        history = [
            {
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"status": ["Only one"]},
            }
        ]

        assert _extract_status_at_date(history, target_date, self.name_to_id) is None

class TestCategorizeStatus:
    def test_none_status_is_backlog(self):
        status_map = {1: {"name": "New", "is_closed": False, "order": 1}}
        assert _categorize_status(None, status_map) == "backlog"

    def test_closed_status_is_done(self):
        status_map = {3: {"name": "Done", "is_closed": True, "order": 3}}
        assert _categorize_status(3, status_map) == "done"

    def test_first_status_is_backlog(self):
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        assert _categorize_status(1, status_map, min_order=1) == "backlog"

    def test_middle_status_is_wip(self):
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        assert _categorize_status(2, status_map, min_order=1) == "wip"

    def test_unknown_status_is_wip(self):
        status_map = {1: {"name": "New", "is_closed": False, "order": 1}}
        assert _categorize_status(999, status_map) == "wip"

    def test_min_order_calculation(self):
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        assert _categorize_status(2, status_map) == "wip"

    def test_string_status_name_done(self):
        status_map = {
            1: {"name": "New", "is_closed": False, "order": 1},
            3: {"name": "Done", "is_closed": True, "order": 3},
        }
        assert _categorize_status("Done", status_map, min_order=1) == "done"

    def test_string_status_name_wip(self):
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        assert _categorize_status("In Progress", status_map, min_order=1) == "wip"

    def test_string_status_name_backlog(self):
        status_map = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        assert _categorize_status("Backlog", status_map, min_order=1) == "backlog"


class TestGetMilestones:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch_with_results_key(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [
                {"id": 1, "name": "Sprint 1"},
                {"id": 2, "name": "Sprint 2"},
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        milestones = _get_milestones(123)
        assert len(milestones) == 2

    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch_list_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [{"id": 1, "name": "Sprint 1"}]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        milestones = _get_milestones(123)
        assert len(milestones) == 1

    @patch("src.metrics.wip.requests.get")
    def test_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("Network error")

        with pytest.raises(TaigaFetchError):
            _get_milestones(123)

    @patch("src.metrics.wip.requests.get")
    def test_empty_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        assert _get_milestones(123) == []


class TestCalculateDailyWip:
    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_successful_calculation(
        self,
        mock_validate,
        mock_project_id,
        mock_sprint_dates,
        mock_statuses,
        mock_stories,
        mock_history,
    ):
        mock_validate.return_value = "my-project"
        mock_project_id.return_value = 123
        mock_sprint_dates.return_value = (date(2024, 1, 1), date(2024, 1, 3))
        mock_statuses.return_value = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        mock_stories.return_value = [
            {"id": 1, "status": 2, "created_date": "2024-01-01T00:00:00Z"}
        ]
        mock_history.return_value = []

        metric = calculate_daily_wip("https://taiga.io/project/my-project", 1)

        assert metric.project_id == 123
        assert metric.project_slug == "my-project"
        assert metric.sprint_id == 1
        assert len(metric.daily_wip) == 3

    @patch("src.metrics.wip._validate_taiga_url")
    def test_invalid_url(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid URL")

        with pytest.raises(ValueError):
            calculate_daily_wip("invalid-url", 1)


class TestCalculateDailyWipAllSprints:
    @patch("src.metrics.wip._validate_taiga_url")
    def test_invalid_url_raises(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid URL")

        with pytest.raises(ValueError):
            calculate_daily_wip_all_sprints("invalid-url")

    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_milestones")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_all_sprints_returns_results(
        self,
        mock_validate,
        mock_project_id,
        mock_statuses,
        mock_milestones,
        mock_sprint_dates,
        mock_stories,
        mock_history,
    ):
        mock_validate.return_value = "my-project"
        mock_project_id.return_value = 123
        mock_statuses.return_value = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        mock_milestones.return_value = [
            {"id": 10, "name": "Sprint 1", "estimated_finish": "2024-01-14"},
            {"id": 20, "name": "Sprint 2", "estimated_finish": "2024-01-28"},
        ]
        mock_sprint_dates.side_effect = [
            (date(2024, 1, 1), date(2024, 1, 2)),
            (date(2024, 1, 15), date(2024, 1, 16)),
        ]
        mock_stories.return_value = [
            {"id": 1, "status": 2, "created_date": "2024-01-01T00:00:00Z"}
        ]
        mock_history.return_value = []

        results = calculate_daily_wip_all_sprints("https://taiga.io/project/my-project")

        assert len(results) == 2
        assert results[0].sprint_name == "Sprint 1"
        assert results[1].sprint_name == "Sprint 2"
        assert results[0].sprint_id == 10
        assert results[1].sprint_id == 20

    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_milestones")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_recent_days_filters_sprints(
        self,
        mock_validate,
        mock_project_id,
        mock_statuses,
        mock_milestones,
        mock_sprint_dates,
        mock_stories,
        mock_history,
    ):
        mock_validate.return_value = "my-project"
        mock_project_id.return_value = 123
        mock_statuses.return_value = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
            2: {"name": "In Progress", "is_closed": False, "order": 2},
        }
        today = date.today()
        old_end = (today - timedelta(days=400)).isoformat()
        recent_end = (today - timedelta(days=5)).isoformat()
        mock_milestones.return_value = [
            {"id": 10, "name": "Old Sprint", "estimated_finish": old_end},
            {"id": 20, "name": "Recent Sprint", "estimated_finish": recent_end},
        ]
        recent_start = today - timedelta(days=19)
        recent_end_date = today - timedelta(days=5)
        mock_sprint_dates.return_value = (recent_start, recent_end_date)
        mock_stories.return_value = []
        mock_history.return_value = []

        results = calculate_daily_wip_all_sprints(
            "https://taiga.io/project/my-project", recent_days=30
        )

        assert len(results) == 1
        assert results[0].sprint_name == "Recent Sprint"

    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_milestones")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_recent_days_fallback_to_latest(
        self,
        mock_validate,
        mock_project_id,
        mock_statuses,
        mock_milestones,
        mock_sprint_dates,
        mock_stories,
        mock_history,
    ):
        mock_validate.return_value = "my-project"
        mock_project_id.return_value = 123
        mock_statuses.return_value = {
            1: {"name": "Backlog", "is_closed": False, "order": 1},
        }
        mock_milestones.return_value = [
            {"id": 10, "name": "Old Sprint 1", "estimated_finish": "2020-01-14"},
            {"id": 20, "name": "Old Sprint 2", "estimated_finish": "2021-06-01"},
        ]
        mock_sprint_dates.return_value = (date(2021, 5, 18), date(2021, 6, 1))
        mock_stories.return_value = []
        mock_history.return_value = []

        results = calculate_daily_wip_all_sprints(
            "https://taiga.io/project/my-project", recent_days=7
        )

        assert len(results) == 1
        assert results[0].sprint_name == "Old Sprint 2"


class TestGetTaskStatuses:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "name": "New", "is_closed": False, "order": 1},
            {"id": 2, "name": "In progress", "is_closed": False, "order": 2},
            {"id": 3, "name": "Closed", "is_closed": True, "order": 3},
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        statuses = _get_task_statuses(123)
        assert len(statuses) == 3
        assert statuses[1]["name"] == "New"
        assert statuses[3]["is_closed"] is True

    @patch("src.metrics.wip.requests.get")
    def test_empty_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError):
            _get_task_statuses(123)


class TestGetTasks:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "status": 2, "created_date": "2024-01-01T00:00:00Z"},
            {"id": 2, "status": 1, "created_date": "2024-01-02T00:00:00Z"},
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        tasks = _get_tasks(123)
        assert len(tasks) == 2

    @patch("src.metrics.wip.requests.get")
    def test_empty_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        assert _get_tasks(123) == []


class TestGetTaskHistory:
    @patch("src.metrics.wip.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                "created_at": "2024-01-01T10:00:00Z",
                "values_diff": {"status": ["New", "In progress"]},
            }
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        history = _get_task_history(1)
        assert len(history) == 1

    @patch("src.metrics.wip.requests.get")
    def test_request_exception_returns_empty(self, mock_get):
        mock_get.side_effect = requests.RequestException("Not found")

        history = _get_task_history(1)
        assert history == []


class TestCalculateKanbanWip:
    @patch("src.metrics.wip._get_task_history")
    @patch("src.metrics.wip._get_tasks")
    @patch("src.metrics.wip._get_task_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_successful_kanban_calculation(
        self,
        mock_validate,
        mock_project_id,
        mock_task_statuses,
        mock_tasks,
        mock_task_history,
    ):
        mock_validate.return_value = "my-project"
        mock_project_id.return_value = 123
        mock_task_statuses.return_value = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "In progress", "is_closed": False, "order": 2},
            3: {"name": "Closed", "is_closed": True, "order": 3},
        }
        mock_tasks.return_value = [
            {"id": 10, "status": 2, "created_date": "2024-01-01T00:00:00Z"},
            {"id": 20, "status": 3, "created_date": "2024-01-01T00:00:00Z"},
        ]
        mock_task_history.return_value = []

        metric = calculate_kanban_wip(
            "https://taiga.io/project/my-project", recent_days=3
        )

        assert metric.project_id == 123
        assert metric.project_slug == "my-project"
        assert metric.sprint_name == "kanban"
        assert len(metric.daily_wip) == 4  # today - 3 days to today inclusive

    @patch("src.metrics.wip._validate_taiga_url")
    def test_invalid_url(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid URL")

        with pytest.raises(ValueError):
            calculate_kanban_wip("invalid-url")

    @patch("src.metrics.wip._get_task_history")
    @patch("src.metrics.wip._get_tasks")
    @patch("src.metrics.wip._get_task_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_kanban_defaults_to_30_days(
        self,
        mock_validate,
        mock_project_id,
        mock_task_statuses,
        mock_tasks,
        mock_task_history,
    ):
        mock_validate.return_value = "my-project"
        mock_project_id.return_value = 123
        mock_task_statuses.return_value = {
            1: {"name": "New", "is_closed": False, "order": 1},
        }
        mock_tasks.return_value = []
        mock_task_history.return_value = []

        metric = calculate_kanban_wip("https://taiga.io/project/my-project")

        assert len(metric.daily_wip) == 31  # 30 days + today

    @patch("src.metrics.wip._get_task_history")
    @patch("src.metrics.wip._get_tasks")
    @patch("src.metrics.wip._get_task_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_kanban_tracks_task_status_changes(
        self,
        mock_validate,
        mock_project_id,
        mock_task_statuses,
        mock_tasks,
        mock_task_history,
    ):
        mock_validate.return_value = "my-project"
        mock_project_id.return_value = 123
        mock_task_statuses.return_value = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "In progress", "is_closed": False, "order": 2},
            3: {"name": "Closed", "is_closed": True, "order": 3},
        }
        today = date.today()
        yesterday = today - timedelta(days=1)
        mock_tasks.return_value = [
            {"id": 10, "status": 1, "created_date": f"{today - timedelta(days=5)}T00:00:00Z"},
        ]
        mock_task_history.return_value = [
            {
                "created_at": f"{yesterday}T10:00:00Z",
                "values_diff": {"status": ["New", "Closed"]},
            }
        ]

        metric = calculate_kanban_wip(
            "https://taiga.io/project/my-project", recent_days=3
        )

        day_before_change = (yesterday - timedelta(days=1)).isoformat()
        change_day = yesterday.isoformat()

        daily_map = {d.date: d for d in metric.daily_wip}
        if day_before_change in daily_map:
            assert daily_map[day_before_change].backlog_count == 1
            assert daily_map[day_before_change].done_count == 0
        assert daily_map[change_day].done_count == 1
        assert daily_map[change_day].backlog_count == 0


    @patch("src.metrics.wip._get_task_history")
    @patch("src.metrics.wip._get_tasks")
    @patch("src.metrics.wip._get_task_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_kanban_shifts_to_last_activity_when_stale(
        self,
        mock_validate,
        mock_project_id,
        mock_task_statuses,
        mock_tasks,
        mock_task_history,
    ):
        mock_validate.return_value = "old-project"
        mock_project_id.return_value = 456
        mock_task_statuses.return_value = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "Done", "is_closed": True, "order": 2},
        }
        mock_tasks.return_value = [
            {"id": 10, "status": 2, "created_date": "2023-01-01T00:00:00Z"},
        ]
        last_activity = (date.today() - timedelta(days=100)).isoformat()
        mock_task_history.return_value = [
            {
                "created_at": f"{last_activity}T12:00:00Z",
                "values_diff": {"status": ["New", "Done"]},
            }
        ]

        metric = calculate_kanban_wip("https://taiga.io/project/old-project")

        assert metric.date_range_end == last_activity
        expected_start = (date.today() - timedelta(days=100) - timedelta(days=30)).isoformat()
        assert metric.date_range_start == expected_start
        assert len(metric.daily_wip) == 31


class TestDataClasses:
    def test_daily_wip_metric(self):
        metric = DailyWIPMetric(
            date="2024-01-01", wip_count=5, backlog_count=10, done_count=3
        )
        assert metric.wip_count == 5
        assert metric.backlog_count == 10

    def test_wip_metric(self):
        daily_wip = [DailyWIPMetric("2024-01-01", 5, 10, 0)]
        metric = WIPMetric(
            project_id=123,
            project_slug="my-project",
            sprint_id=1,
            daily_wip=daily_wip,
        )
        assert len(metric.daily_wip) == 1
        assert metric.project_id == 123


class TestAdditionalCoverage:

    def test_url_with_project_but_empty_after(self):
        with pytest.raises(ValueError):
            _validate_taiga_url("https://taiga.io/project/")

    def test_url_multiple_project_segments(self):
        url = "https://taiga.io/project/slug1/project/slug2"
        with pytest.raises(ValueError):
            _validate_taiga_url(url)

    @patch("src.metrics.wip.requests.get")
    def test_get_project_id_type_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.side_effect = TypeError("bad json")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError, match="Unexpected API"):
            _get_project_id("slug")

    @patch("src.metrics.wip.requests.get")
    def test_get_userstories_request_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")

        with pytest.raises(TaigaFetchError, match="Failed to fetch userstories"):
            _get_userstories(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_userstories_type_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.side_effect = TypeError("bad")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError, match="Unexpected API"):
            _get_userstories(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_userstories_with_milestone(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [{"id": 1}]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = _get_userstories(123, milestone=456)
        assert len(result) == 1
        mock_get.assert_called_once()
        call_params = mock_get.call_args[1].get("params") or mock_get.call_args[0][0] if mock_get.call_args[0] else {}
        actual_params = mock_get.call_args.kwargs.get("params", {})
        assert actual_params.get("milestone") == 456

    @patch("src.metrics.wip.requests.get")
    def test_get_userstory_history_type_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.side_effect = TypeError("bad")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = _get_userstory_history(1)
        assert result == []

    @patch("src.metrics.wip.requests.get")
    def test_get_userstory_history_non_list(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"error": "not a list"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = _get_userstory_history(1)
        assert result == []

    @patch("src.metrics.wip.requests.get")
    def test_get_project_statuses_type_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.side_effect = TypeError("bad")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError, match="Unexpected API"):
            _get_project_statuses(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_sprint_dates_bad_date_format(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {
            "estimated_start": "not-a-date",
            "estimated_finish": "2024-01-14",
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError, match="Invalid sprint date"):
            _get_sprint_dates(123, 1)

    def test_extract_status_at_date_bad_datetime(self):
        history = [
            {"created_at": "not-a-date", "values_diff": {"status": ["A", "B"]}},
        ]
        result = _extract_status_at_date(history, date(2024, 1, 1))
        assert result is None

    def test_extract_status_at_date_empty_created_at(self):
        history = [
            {"created_at": "", "values_diff": {"status": ["A", "B"]}},
        ]
        result = _extract_status_at_date(history, date(2024, 1, 1))
        assert result is None

    def test_categorize_status_auto_min_order_backlog(self):
        status_map = {
            5: {"name": "Todo", "is_closed": False, "order": 5},
            10: {"name": "WIP", "is_closed": False, "order": 10},
        }
        assert _categorize_status(5, status_map) == "backlog"

    def test_categorize_status_unknown_string_name(self):
        status_map = {1: {"name": "New", "is_closed": False, "order": 1}}
        assert _categorize_status("NonExistent", status_map, min_order=1) == "wip"

    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_scrum_story_with_no_created_date(
        self, mock_validate, mock_pid, mock_dates, mock_statuses, mock_stories, mock_hist
    ):
        mock_validate.return_value = "proj"
        mock_pid.return_value = 1
        mock_dates.return_value = (date(2024, 1, 1), date(2024, 1, 1))
        mock_statuses.return_value = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "WIP", "is_closed": False, "order": 2},
        }
        mock_stories.return_value = [{"id": 1, "status": 2}]
        mock_hist.return_value = []

        metric = calculate_daily_wip("https://taiga.io/project/proj", 1)
        assert metric.daily_wip[0].wip_count == 1

    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_scrum_story_with_bad_created_date(
        self, mock_validate, mock_pid, mock_dates, mock_statuses, mock_stories, mock_hist
    ):
        mock_validate.return_value = "proj"
        mock_pid.return_value = 1
        mock_dates.return_value = (date(2024, 1, 1), date(2024, 1, 1))
        mock_statuses.return_value = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "WIP", "is_closed": False, "order": 2},
        }
        mock_stories.return_value = [
            {"id": 1, "status": 2, "created_date": "not-a-date"}
        ]
        mock_hist.return_value = []

        metric = calculate_daily_wip("https://taiga.io/project/proj", 1)
        assert metric.daily_wip[0].wip_count == 1

    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_scrum_story_not_yet_created(
        self, mock_validate, mock_pid, mock_dates, mock_statuses, mock_stories, mock_hist
    ):
        mock_validate.return_value = "proj"
        mock_pid.return_value = 1
        mock_dates.return_value = (date(2024, 1, 1), date(2024, 1, 2))
        mock_statuses.return_value = {
            1: {"name": "New", "is_closed": False, "order": 1},
        }
        mock_stories.return_value = [
            {"id": 1, "status": 1, "created_date": "2024-01-02T00:00:00Z"}
        ]
        mock_hist.return_value = []

        metric = calculate_daily_wip("https://taiga.io/project/proj", 1)
        assert metric.daily_wip[0].backlog_count == 1
        assert metric.daily_wip[1].backlog_count == 1

    @patch("src.metrics.wip._validate_taiga_url")
    def test_calculate_daily_wip_unexpected_error(self, mock_validate):
        mock_validate.side_effect = RuntimeError("unexpected")

        with pytest.raises(TaigaFetchError, match="Unexpected error"):
            calculate_daily_wip("https://taiga.io/project/x", 1)

    @patch("src.metrics.wip._get_userstory_history")
    @patch("src.metrics.wip._get_userstories")
    @patch("src.metrics.wip._get_sprint_dates")
    @patch("src.metrics.wip._get_milestones")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_all_sprints_milestone_without_id(
        self, mock_val, mock_pid, mock_stat, mock_ms, mock_sd, mock_us, mock_uh
    ):
        mock_val.return_value = "p"
        mock_pid.return_value = 1
        mock_stat.return_value = {1: {"name": "New", "is_closed": False, "order": 1}}
        mock_ms.return_value = [{"name": "No ID sprint"}]  # no "id" key
        mock_sd.return_value = (date(2024, 1, 1), date(2024, 1, 1))
        mock_us.return_value = []
        mock_uh.return_value = []

        results = calculate_daily_wip_all_sprints("https://taiga.io/project/p")
        assert len(results) == 0  # skipped because no id

    @patch("src.metrics.wip._validate_taiga_url")
    def test_all_sprints_unexpected_error(self, mock_validate):
        mock_validate.side_effect = RuntimeError("boom")

        with pytest.raises(TaigaFetchError, match="Unexpected error"):
            calculate_daily_wip_all_sprints("https://taiga.io/project/x")

    @patch("src.metrics.wip._get_task_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_kanban_taiga_fetch_error(self, mock_val, mock_pid, mock_ts):
        mock_val.return_value = "slug"
        mock_pid.return_value = 1
        mock_ts.side_effect = TaigaFetchError("no statuses")

        with pytest.raises(TaigaFetchError, match="no statuses"):
            calculate_kanban_wip("https://taiga.io/project/slug")

    @patch("src.metrics.wip._validate_taiga_url")
    def test_kanban_unexpected_error(self, mock_val):
        mock_val.side_effect = RuntimeError("boom")

        with pytest.raises(TaigaFetchError, match="Unexpected error"):
            calculate_kanban_wip("https://taiga.io/project/x")

    @patch("src.metrics.wip.requests.get")
    def test_get_task_statuses_request_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")

        with pytest.raises(TaigaFetchError, match="Failed to fetch task statuses"):
            _get_task_statuses(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_task_statuses_type_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.side_effect = TypeError("bad")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError, match="Unexpected API"):
            _get_task_statuses(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_tasks_request_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")

        with pytest.raises(TaigaFetchError, match="Failed to fetch tasks"):
            _get_tasks(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_tasks_type_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.side_effect = TypeError("bad")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError, match="Unexpected API"):
            _get_tasks(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_tasks_non_list(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"items": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        assert _get_tasks(123) == []

    @patch("src.metrics.wip.requests.get")
    def test_get_task_history_type_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.side_effect = TypeError("bad")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = _get_task_history(1)
        assert result == []

    @patch("src.metrics.wip.requests.get")
    def test_get_task_history_non_list(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"error": "not a list"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = _get_task_history(1)
        assert result == []

    @patch("src.metrics.wip.requests.get")
    def test_get_milestones_type_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.side_effect = TypeError("bad")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TaigaFetchError, match="Unexpected API"):
            _get_milestones(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_milestones_request_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")

        with pytest.raises(TaigaFetchError, match="Failed to fetch milestones"):
            _get_milestones(123)

    @patch("src.metrics.wip.requests.get")
    def test_get_milestones_non_dict_non_list(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = 42
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = _get_milestones(123)
        assert result == []

    @patch("src.metrics.wip._get_task_history")
    @patch("src.metrics.wip._get_tasks")
    @patch("src.metrics.wip._get_task_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_kanban_task_no_created_date(
        self, mock_val, mock_pid, mock_ts, mock_tasks, mock_th
    ):
        mock_val.return_value = "proj"
        mock_pid.return_value = 1
        mock_ts.return_value = {
            1: {"name": "New", "is_closed": False, "order": 1},
            2: {"name": "WIP", "is_closed": False, "order": 2},
        }
        mock_tasks.return_value = [{"id": 10, "status": 2}]
        mock_th.return_value = []

        metric = calculate_kanban_wip("https://taiga.io/project/proj", recent_days=1)
        assert metric.daily_wip[0].wip_count == 1

    @patch("src.metrics.wip.requests.get")
    def test_get_sprint_dates_request_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")

        with pytest.raises(TaigaFetchError, match="Failed to fetch sprint dates"):
            _get_sprint_dates(123, 1)

    @patch("src.metrics.wip.requests.get")
    def test_get_project_statuses_request_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")

        with pytest.raises(TaigaFetchError, match="Failed to fetch statuses"):
            _get_project_statuses(123)

    def test_build_status_name_to_id_skips_empty_names(self):
        status_map = {
            1: {"name": "Backlog", "is_closed": False},
            2: {"name": "", "is_closed": False},
            3: {},
        }
        result = _build_status_name_to_id(status_map)
        assert result == {"Backlog": 1}

    @patch("src.metrics.wip._get_milestones")
    @patch("src.metrics.wip._get_project_statuses")
    @patch("src.metrics.wip._get_project_id")
    @patch("src.metrics.wip._validate_taiga_url")
    def test_all_sprints_recent_days_bad_milestone_date(
        self, mock_val, mock_pid, mock_stat, mock_ms
    ):
        mock_val.return_value = "proj"
        mock_pid.return_value = 1
        mock_stat.return_value = {1: {"name": "New", "is_closed": False, "order": 1}}
        mock_ms.return_value = [
            {"id": 10, "name": "Bad Date Sprint", "estimated_finish": "not-a-date"},
        ]

        with pytest.raises(ValueError):
            calculate_daily_wip_all_sprints(
                "https://taiga.io/project/proj", recent_days=30
            )


class TestTaigaFetchError:
    def test_exception_creation(self):
        error = TaigaFetchError("Test error")
        assert str(error) == "Test error"

    def test_exception_raise(self):
        with pytest.raises(TaigaFetchError):
            raise TaigaFetchError("Test")
