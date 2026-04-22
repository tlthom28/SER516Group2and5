"""
US-186 / Task #199: Found work metrics — get_found_work() service and OTel logging.
"""
import logging
import pytest
from unittest.mock import Mock, patch

from src.services.taiga_metrics import get_found_work


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project_responses(project_data, sprint_data, user_story_data, task_data=None):
    """Build requests.get side_effect list for get_structure calls."""
    task_data = task_data or []
    return [
        Mock(status_code=200, json=lambda pd=project_data: pd),
        Mock(status_code=200, json=lambda sd=sprint_data: sd),
        Mock(status_code=200, json=lambda ud=user_story_data: ud),
        Mock(status_code=200, json=lambda td=task_data: td),
    ]


def _base_data():
    project_data = {
        "id": 1,
        "name": "Demo Project",
        "created_date": "2024-01-01T00:00:00Z",
    }
    sprint_data = [
        {
            "id": 10,
            "name": "Sprint 1",
            "estimated_start": "2024-01-08T00:00:00Z",
            "estimated_finish": "2024-01-21T00:00:00Z",
        }
    ]
    user_story_data = [
        {
            "id": 200,
            "subject": "Pre-sprint story",
            "milestone": 10,
            "created_date": "2024-01-01T00:00:00Z",
        },
        {
            "id": 201,
            "subject": "Found story",
            "milestone": 10,
            "created_date": "2024-01-10T00:00:00Z",
        },
    ]
    return project_data, sprint_data, user_story_data


# ---------------------------------------------------------------------------
# 1. Return structure
# ---------------------------------------------------------------------------

class TestFoundWorkReturnStructure:
    """Verify the shape of the value returned by get_found_work."""

    def test_success_status(self):
        project_data, sprint_data, user_story_data = _base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            result = get_found_work("", "", -1)

        assert result["status"] == "success"
        assert "sprints" in result

    def test_sprint_keys_present(self):
        project_data, sprint_data, user_story_data = _base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            result = get_found_work("", "", -1)

        sprint = result["sprints"][0]
        assert "sprint_name" in sprint
        assert "sprint_id" in sprint
        assert "found_count" in sprint
        assert "found_stories" in sprint

    def test_found_count_correct(self):
        """Only story 201 (created after sprint start) should be counted."""
        project_data, sprint_data, user_story_data = _base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            result = get_found_work("", "", -1)

        assert result["sprints"][0]["found_count"] == 1
        assert result["sprints"][0]["found_stories"][0]["user_story_id"] == 201

    def test_story_keys_present(self):
        project_data, sprint_data, user_story_data = _base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            result = get_found_work("", "", -1)

        story = result["sprints"][0]["found_stories"][0]
        assert "user_story_name" in story
        assert "user_story_id" in story
        assert "created_date" in story

    def test_no_found_work_when_all_preplanned(self):
        """Stories created before sprint start should not be counted as found work."""
        project_data, sprint_data, _ = _base_data()
        user_story_data = [
            {
                "id": 300,
                "subject": "Old story",
                "milestone": 10,
                "created_date": "2024-01-01T00:00:00Z",
            }
        ]

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            result = get_found_work("", "", -1)

        assert result["sprints"][0]["found_count"] == 0
        assert result["sprints"][0]["found_stories"] == []

    def test_error_on_bad_project(self):
        """An error dict is returned when get_structure fails."""
        with patch("src.services.taiga_metrics.get_structure") as mock_gs:
            mock_gs.return_value = "Error: Taiga response code 404"
            result = get_found_work("", "", -1)

        assert result["status"] == "error"

    def test_multiple_sprints(self):
        """Found work is computed independently per sprint."""
        project_data = {
            "id": 1,
            "name": "Multi Sprint Project",
            "created_date": "2024-01-01T00:00:00Z",
        }
        sprint_data = [
            {
                "id": 10,
                "name": "Sprint 1",
                "estimated_start": "2024-01-08T00:00:00Z",
                "estimated_finish": "2024-01-21T00:00:00Z",
            },
            {
                "id": 20,
                "name": "Sprint 2",
                "estimated_start": "2024-01-22T00:00:00Z",
                "estimated_finish": "2024-02-04T00:00:00Z",
            },
        ]
        user_story_data = [
            {"id": 100, "subject": "Planned S1", "milestone": 10, "created_date": "2024-01-01T00:00:00Z"},
            {"id": 101, "subject": "Found S1",   "milestone": 10, "created_date": "2024-01-10T00:00:00Z"},
            {"id": 200, "subject": "Planned S2", "milestone": 20, "created_date": "2024-01-15T00:00:00Z"},
            {"id": 201, "subject": "Found S2a",  "milestone": 20, "created_date": "2024-01-25T00:00:00Z"},
            {"id": 202, "subject": "Found S2b",  "milestone": 20, "created_date": "2024-01-28T00:00:00Z"},
        ]

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            result = get_found_work("", "", -1)

        assert result["status"] == "success"
        counts = {s["sprint_id"]: s["found_count"] for s in result["sprints"]}
        assert counts[10] == 1
        assert counts[20] == 2


# ---------------------------------------------------------------------------
# 2. OTel structured logging
# ---------------------------------------------------------------------------

class TestFoundWorkLogging:
    """Verify that get_found_work emits structured OTel-compatible log records."""

    def test_found_story_info_logged(self, caplog):
        project_data, sprint_data, user_story_data = _base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                result = get_found_work("", "", -1)

        assert result["status"] == "success"
        found_logs = [r for r in caplog.records if "Found work story detected" in r.message]
        assert len(found_logs) == 1
        assert "201" in found_logs[0].message

    def test_sprint_summary_logged(self, caplog):
        project_data, sprint_data, user_story_data = _base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                get_found_work("", "", -1)

        summary_logs = [r for r in caplog.records if "Sprint found work summary" in r.message]
        assert len(summary_logs) == 1
        assert "Sprint 1" in summary_logs[0].message
        assert "found_count=1" in summary_logs[0].message

    def test_completion_summary_logged(self, caplog):
        project_data, sprint_data, user_story_data = _base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                get_found_work("", "", -1)

        completion_logs = [
            r for r in caplog.records if "Found work computation complete" in r.message
        ]
        assert len(completion_logs) == 1
        assert "total_sprints=1" in completion_logs[0].message

    def test_project_structure_info_logged(self, caplog):
        project_data, sprint_data, user_story_data = _base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                get_found_work("", "", -1)

        structure_logs = [
            r for r in caplog.records if "Fetched Taiga project structure for found work" in r.message
        ]
        assert len(structure_logs) == 1
        assert "Demo Project" in structure_logs[0].message

    def test_no_found_log_when_no_found_stories(self, caplog):
        project_data, sprint_data, _ = _base_data()
        user_story_data = [
            {"id": 300, "subject": "Old", "milestone": 10, "created_date": "2024-01-01T00:00:00Z"}
        ]

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                result = get_found_work("", "", -1)

        assert result["sprints"][0]["found_count"] == 0
        found_logs = [r for r in caplog.records if "Found work story detected" in r.message]
        assert len(found_logs) == 0

    def test_error_path_logs_error(self, caplog):
        with patch("src.services.taiga_metrics.get_structure") as mock_gs:
            mock_gs.return_value = "Error: Taiga response code 500"
            with caplog.at_level(logging.ERROR, logger="repopulse.services.taiga_metrics"):
                result = get_found_work("", "", -1)

        assert result["status"] == "error"
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_logs) >= 1
        assert any("500" in r.message for r in error_logs)
