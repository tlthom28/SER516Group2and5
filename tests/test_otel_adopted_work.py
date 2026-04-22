"""
US-186 / Task #199: OpenTelemetry implementation for adopted/found work.
"""
import logging
import pytest
from unittest.mock import Mock, patch

from src.services.taiga_metrics import get_adopted_work


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _make_project_responses(
    project_data,
    sprint_data,
    user_story_data,
    task_data=None,
):
    """Build the side_effect list for requests.get calls made by get_structure."""
    task_data = task_data or []
    return [
        Mock(status_code=200, json=lambda pd=project_data: pd),
        Mock(status_code=200, json=lambda sd=sprint_data: sd),
        Mock(status_code=200, json=lambda ud=user_story_data: ud),
        Mock(status_code=200, json=lambda td=task_data: td),
    ]


# ---------------------------------------------------------------------------
# 1. Logger existence
# ---------------------------------------------------------------------------

class TestTaigaMetricsLoggerExists:
    """Verify the module-level logger is configured correctly."""

    def test_logger_name(self):
        import src.services.taiga_metrics as mod
        assert hasattr(mod, "logger")
        assert mod.logger.name == "repopulse.services.taiga_metrics"


# ---------------------------------------------------------------------------
# 2. Adopted stories emit INFO log entries
# ---------------------------------------------------------------------------

class TestAdoptedWorkLogging:
    """Verify that get_adopted_work emits structured log messages."""

    def _base_data(self):
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
                "id": 100,
                "subject": "Pre-sprint story",
                "milestone": 10,
                "created_date": "2024-01-01T00:00:00Z",
            },
            {
                "id": 101,
                "subject": "Adopted story",
                "milestone": 10,
                "created_date": "2024-01-10T00:00:00Z",
            },
        ]
        return project_data, sprint_data, user_story_data

    def test_adopted_story_info_logged(self, caplog):
        """An INFO line should be emitted for each adopted story."""
        project_data, sprint_data, user_story_data = self._base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                result = get_adopted_work("", "", -1)

        assert result["status"] == "success"
        adopted_logs = [r for r in caplog.records if "Adopted story detected" in r.message]
        assert len(adopted_logs) == 1
        assert "101" in adopted_logs[0].message

    def test_sprint_summary_logged(self, caplog):
        """An INFO line with the sprint adopted_count should be logged."""
        project_data, sprint_data, user_story_data = self._base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                get_adopted_work("", "", -1)

        summary_logs = [r for r in caplog.records if "Sprint adopted work summary" in r.message]
        assert len(summary_logs) == 1
        assert "Sprint 1" in summary_logs[0].message
        assert "adopted_count=1" in summary_logs[0].message

    def test_completion_summary_logged(self, caplog):
        """A completion INFO log should appear after all sprints are processed."""
        project_data, sprint_data, user_story_data = self._base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                get_adopted_work("", "", -1)

        completion_logs = [
            r for r in caplog.records if "Adopted work computation complete" in r.message
        ]
        assert len(completion_logs) == 1
        assert "total_sprints=1" in completion_logs[0].message

    def test_project_structure_info_logged(self, caplog):
        """An INFO log confirming the project structure fetch should be emitted."""
        project_data, sprint_data, user_story_data = self._base_data()

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                get_adopted_work("", "", -1)

        structure_logs = [
            r for r in caplog.records if "Fetched Taiga project structure" in r.message
        ]
        assert len(structure_logs) == 1
        assert "Demo Project" in structure_logs[0].message

    def test_no_adopted_stories_no_adopted_log(self, caplog):
        """When all stories predate sprint start, no adopted-story log should appear."""
        project_data = {
            "id": 1,
            "name": "Demo",
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
                "id": 100,
                "subject": "Old story",
                "milestone": 10,
                "created_date": "2024-01-01T00:00:00Z",
            }
        ]

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                result = get_adopted_work("", "", -1)

        assert result["sprints"][0]["adopted_count"] == 0
        adopted_logs = [r for r in caplog.records if "Adopted story detected" in r.message]
        assert len(adopted_logs) == 0

    def test_error_path_logs_error(self, caplog):
        """When the project structure fetch fails, an ERROR log should be emitted."""
        with patch("src.services.taiga_metrics.get_structure") as mock_gs:
            mock_gs.return_value = "Error: Taiga response code 404"
            with caplog.at_level(logging.ERROR, logger="repopulse.services.taiga_metrics"):
                result = get_adopted_work("", "", -1)

        assert result["status"] == "error"
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_logs) >= 1
        assert any("404" in r.message for r in error_logs)

    def test_multiple_sprints_summary_counts(self, caplog):
        """Each sprint should emit its own summary log."""
        project_data = {
            "id": 1,
            "name": "Multi Sprint",
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
            {"id": 100, "subject": "S1 story", "milestone": 10, "created_date": "2024-01-10T00:00:00Z"},
            {"id": 200, "subject": "S2 story", "milestone": 20, "created_date": "2024-01-24T00:00:00Z"},
        ]

        with patch("src.services.taiga_metrics.requests.get") as mock_get:
            mock_get.side_effect = _make_project_responses(
                project_data, sprint_data, user_story_data
            )
            with caplog.at_level(logging.INFO, logger="repopulse.services.taiga_metrics"):
                result = get_adopted_work("", "", -1)

        assert result["status"] == "success"
        summary_logs = [r for r in caplog.records if "Sprint adopted work summary" in r.message]
        assert len(summary_logs) == 2
        sprint_names_logged = {r.message for r in summary_logs}
        assert any("Sprint 1" in m for m in sprint_names_logged)
        assert any("Sprint 2" in m for m in sprint_names_logged)
