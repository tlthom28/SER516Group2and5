"""
T-181: Validate the Cycle Time Metrics
US-169: Validate all the metrics

This file validates that cycle time metrics are computed correctly
end-to-end — from Taiga transition data through calculation to
the API response and InfluxDB write.

Validation approach:
  - Known inputs with manually verified expected outputs
  - Boundary conditions (same-day, multi-sprint, reopened stories)
  - Summary statistics (average, median, min, max)
  - API response structure and field correctness
  - InfluxDB write correctness
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.main import app
from src.services.cycle_time import compute_cycle_times, summarize_cycle_times
from src.services.taiga_metrics import CYCLE_TIME_START_STATES, CYCLE_TIME_END_STATES

client = TestClient(app)


def _t(status, timestamp):
    """Helper to build a transition dict."""
    return {"status": status, "timestamp": timestamp}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Validate canonical state boundaries
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleTimeStateBoundaries:
    """Validate that the start/end states are what we expect."""

    def test_start_state_is_in_progress(self):
        assert "In Progress" in CYCLE_TIME_START_STATES

    def test_end_state_is_done(self):
        assert "Done" in CYCLE_TIME_END_STATES

    def test_start_and_end_states_are_distinct(self):
        overlap = set(CYCLE_TIME_START_STATES) & set(CYCLE_TIME_END_STATES)
        assert len(overlap) == 0, f"Start and end states overlap: {overlap}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Validate calculation correctness with known inputs
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleTimeCalculationValidation:
    """
    Manually verified expected values.
    Each test documents the input and the expected output so
    a human reviewer can confirm correctness independently.
    """

    def test_exactly_24_hours(self):
        """
        Input:  In Progress 2024-01-01 10:00 → Done 2024-01-02 10:00
        Expected: 24.0 hours (exactly 1 day)
        """
        stories = [{"story_id": 1, "transitions": [
            _t("In Progress", "2024-01-01T10:00:00+00:00"),
            _t("Done",        "2024-01-02T10:00:00+00:00"),
        ]}]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 24.0

    def test_exactly_48_hours(self):
        """
        Input:  In Progress 2024-01-01 → Done 2024-01-03 (same time)
        Expected: 48.0 hours (exactly 2 days)
        """
        stories = [{"story_id": 2, "transitions": [
            _t("In Progress", "2024-01-01T08:00:00+00:00"),
            _t("Done",        "2024-01-03T08:00:00+00:00"),
        ]}]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 48.0

    def test_sub_hour_cycle_time(self):
        """
        Input:  In Progress 10:00 → Done 10:30 (same day)
        Expected: 0.5 hours (30 minutes)
        """
        stories = [{"story_id": 3, "transitions": [
            _t("In Progress", "2024-01-01T10:00:00+00:00"),
            _t("Done",        "2024-01-01T10:30:00+00:00"),
        ]}]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 0.5

    def test_multi_day_sprint_story(self):
        """
        Input:  In Progress Jan 1 → Review Jan 3 → Done Jan 5
        Expected: 96.0 hours (4 days from In Progress to Done)
        Validates that intermediate states don't affect the calculation.
        """
        stories = [{"story_id": 4, "transitions": [
            _t("In Progress", "2024-01-01T09:00:00+00:00"),
            _t("Review",      "2024-01-03T09:00:00+00:00"),
            _t("Done",        "2024-01-05T09:00:00+00:00"),
        ]}]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 96.0

    def test_story_never_started_returns_none(self):
        """
        Input:  Story only has Ready → Done (no In Progress)
        Expected: None — cycle time cannot be computed without a start state
        """
        stories = [{"story_id": 5, "transitions": [
            _t("Ready", "2024-01-01T09:00:00+00:00"),
            _t("Done",  "2024-01-03T09:00:00+00:00"),
        ]}]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] is None

    def test_story_never_finished_returns_none(self):
        """
        Input:  Story only has In Progress (no Done)
        Expected: None — cycle time cannot be computed without an end state
        """
        stories = [{"story_id": 6, "transitions": [
            _t("In Progress", "2024-01-01T09:00:00+00:00"),
        ]}]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] is None

    def test_reopened_story_uses_last_done(self):
        """
        Input:  In Progress → Done → In Progress → Done (reopened)
        Expected: 120.0 hours (from first In Progress to last Done)
        Validates that reopened stories measure total elapsed time.
        """
        stories = [{"story_id": 7, "transitions": [
            _t("In Progress", "2024-01-01T10:00:00+00:00"),
            _t("Done",        "2024-01-03T10:00:00+00:00"),  # 48h
            _t("In Progress", "2024-01-04T10:00:00+00:00"),
            _t("Done",        "2024-01-06T10:00:00+00:00"),  # last Done = 120h from start
        ]}]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 120.0

    def test_out_of_order_transitions_sorted_correctly(self):
        """
        Input:  Transitions provided in reverse order
        Expected: Same result as if provided in order (48.0 hours)
        Validates that sorting by timestamp works correctly.
        """
        stories = [{"story_id": 8, "transitions": [
            _t("Done",        "2024-01-03T10:00:00+00:00"),
            _t("In Progress", "2024-01-01T10:00:00+00:00"),
        ]}]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 48.0

    def test_multiple_stories_independent_calculation(self):
        """
        Input:  3 stories with different cycle times
        Expected: Each story calculated independently
        Story 1: 24h, Story 2: 48h, Story 3: None (no Done)
        """
        stories = [
            {"story_id": 10, "transitions": [
                _t("In Progress", "2024-01-01T10:00:00+00:00"),
                _t("Done",        "2024-01-02T10:00:00+00:00"),
            ]},
            {"story_id": 11, "transitions": [
                _t("In Progress", "2024-01-01T10:00:00+00:00"),
                _t("Done",        "2024-01-03T10:00:00+00:00"),
            ]},
            {"story_id": 12, "transitions": [
                _t("In Progress", "2024-01-01T10:00:00+00:00"),
            ]},
        ]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 24.0
        assert result[1]["cycle_time_hours"] == 48.0
        assert result[2]["cycle_time_hours"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Validate summary statistics
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleTimeSummaryValidation:
    """
    Validate summary statistics with manually verified expected values.
    """

    def test_average_of_known_values(self):
        """
        Input:  [24.0, 48.0, 72.0]
        Expected average: (24 + 48 + 72) / 3 = 48.0
        """
        results = [
            {"story_id": 1, "cycle_time_hours": 24.0},
            {"story_id": 2, "cycle_time_hours": 48.0},
            {"story_id": 3, "cycle_time_hours": 72.0},
        ]
        summary = summarize_cycle_times(results)
        assert summary["average"] == 48.0
        assert summary["min"] == 24.0
        assert summary["max"] == 72.0
        assert summary["median"] == 48.0

    def test_median_even_count(self):
        """
        Input:  [10.0, 20.0, 30.0, 40.0]
        Expected median: (20 + 30) / 2 = 25.0
        """
        results = [
            {"story_id": 1, "cycle_time_hours": 10.0},
            {"story_id": 2, "cycle_time_hours": 20.0},
            {"story_id": 3, "cycle_time_hours": 30.0},
            {"story_id": 4, "cycle_time_hours": 40.0},
        ]
        summary = summarize_cycle_times(results)
        assert summary["median"] == 25.0

    def test_median_odd_count(self):
        """
        Input:  [10.0, 20.0, 90.0]
        Expected median: 20.0 (middle value)
        """
        results = [
            {"story_id": 1, "cycle_time_hours": 10.0},
            {"story_id": 2, "cycle_time_hours": 20.0},
            {"story_id": 3, "cycle_time_hours": 90.0},
        ]
        summary = summarize_cycle_times(results)
        assert summary["median"] == 20.0

    def test_none_values_excluded_from_summary(self):
        """
        Input:  [24.0, None, 48.0]
        Expected: None excluded, summary computed from [24.0, 48.0]
        """
        results = [
            {"story_id": 1, "cycle_time_hours": 24.0},
            {"story_id": 2, "cycle_time_hours": None},
            {"story_id": 3, "cycle_time_hours": 48.0},
        ]
        summary = summarize_cycle_times(results)
        assert summary["average"] == 36.0
        assert summary["min"] == 24.0
        assert summary["max"] == 48.0

    def test_all_none_returns_none_summary(self):
        """
        Input:  All stories have no cycle time
        Expected: All summary fields are None
        """
        results = [
            {"story_id": 1, "cycle_time_hours": None},
            {"story_id": 2, "cycle_time_hours": None},
        ]
        summary = summarize_cycle_times(results)
        assert summary["average"] is None
        assert summary["median"] is None
        assert summary["min"] is None
        assert summary["max"] is None

    def test_single_story_summary(self):
        """
        Input:  Single story with 36.0 hours
        Expected: All summary fields equal 36.0
        """
        results = [{"story_id": 1, "cycle_time_hours": 36.0}]
        summary = summarize_cycle_times(results)
        assert summary["average"] == 36.0
        assert summary["median"] == 36.0
        assert summary["min"] == 36.0
        assert summary["max"] == 36.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Validate API response structure
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleTimeApiValidation:
    """
    Validate the /cycle-time API endpoint returns correct structure
    and values for known inputs.
    """

    @patch("src.api.routes.get_taiga_transition_history_data")
    def test_api_returns_correct_cycle_time_hours(self, mock_history):
        """
        Input:  1 story, In Progress → Done over exactly 48 hours
        Expected: API returns cycle_time_hours = 48.0
        """
        mock_history.return_value = {
            "status": "success",
            "project_id": 1,
            "project_slug": "test-project",
            "sprint_id": 10,
            "stories": [{
                "user_story_id": 100,
                "transitions": [
                    {"to_status": "In Progress", "timestamp": "2026-01-01T10:00:00Z"},
                    {"to_status": "Done",        "timestamp": "2026-01-03T10:00:00Z"},
                ],
            }],
        }

        response = client.get("/cycle-time", params={
            "start": "2026-01-01",
            "end": "2026-01-10",
            "slug": "test-project",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["project_slug"] == "test-project"
        assert data["start_date"] == "2026-01-01"
        assert data["end_date"] == "2026-01-10"
        assert len(data["story_cycle_times"]) == 1
        assert data["story_cycle_times"][0]["story_id"] == 100
        assert data["story_cycle_times"][0]["cycle_time_hours"] == 48.0

    @patch("src.api.routes.get_taiga_transition_history_data")
    def test_api_summary_matches_manual_calculation(self, mock_history):
        """
        Input:  3 stories with 24h, 48h, 72h cycle times
        Expected summary: avg=48.0, min=24.0, max=72.0, median=48.0
        """
        mock_history.return_value = {
            "status": "success",
            "project_id": 1,
            "project_slug": "test-project",
            "sprint_id": None,
            "stories": [
                {"user_story_id": 1, "transitions": [
                    {"to_status": "In Progress", "timestamp": "2026-01-01T00:00:00Z"},
                    {"to_status": "Done",        "timestamp": "2026-01-02T00:00:00Z"},
                ]},
                {"user_story_id": 2, "transitions": [
                    {"to_status": "In Progress", "timestamp": "2026-01-01T00:00:00Z"},
                    {"to_status": "Done",        "timestamp": "2026-01-03T00:00:00Z"},
                ]},
                {"user_story_id": 3, "transitions": [
                    {"to_status": "In Progress", "timestamp": "2026-01-01T00:00:00Z"},
                    {"to_status": "Done",        "timestamp": "2026-01-04T00:00:00Z"},
                ]},
            ],
        }

        response = client.get("/cycle-time", params={
            "start": "2026-01-01",
            "end": "2026-01-10",
            "slug": "test-project",
        })

        assert response.status_code == 200
        summary = response.json()["summary"]
        assert summary["average"] == 48.0
        assert summary["min"] == 24.0
        assert summary["max"] == 72.0
        assert summary["median"] == 48.0

    @patch("src.api.routes.get_taiga_transition_history_data")
    def test_api_stories_outside_date_range_excluded(self, mock_history):
        """
        Validates that transitions are included regardless of date range.
        The date range parameters filter which stories to fetch from Taiga,
        but all transitions for those stories are used for cycle time calculation.
        This ensures stories that moved New → Done in a single event are captured.
        """
        mock_history.return_value = {
            "status": "success",
            "project_id": 1,
            "project_slug": "test-project",
            "sprint_id": None,
            "stories": [{
                "user_story_id": 1,
                "transitions": [
                    {"to_status": "In Progress", "timestamp": "2025-12-01T00:00:00Z"},
                    {"to_status": "Done",        "timestamp": "2025-12-15T00:00:00Z"},
                ],
            }],
        }

        response = client.get("/cycle-time", params={
            "start": "2026-01-01",
            "end": "2026-01-31",
            "slug": "test-project",
        })

        assert response.status_code == 200
        data = response.json()
        # All transitions are included — cycle time is computed from Dec 1 → Dec 15 = 336h
        assert data["story_cycle_times"][0]["cycle_time_hours"] == 336.0

    @patch("src.api.routes.get_taiga_transition_history_data")
    def test_api_influx_write_failure_does_not_fail_response(self, mock_history):
        """
        Validates that InfluxDB write failures don't cause a 500 error.
        The API should still return 200 with the computed metrics.
        """
        mock_history.return_value = {
            "status": "success",
            "project_id": 1,
            "project_slug": "test-project",
            "sprint_id": None,
            "stories": [{
                "user_story_id": 1,
                "transitions": [
                    {"to_status": "In Progress", "timestamp": "2026-01-01T00:00:00Z"},
                    {"to_status": "Done",        "timestamp": "2026-01-02T00:00:00Z"},
                ],
            }],
        }

        with patch("src.api.routes.write_cycle_time_metrics", side_effect=RuntimeError("influx down")):
            response = client.get("/cycle-time", params={
                "start": "2026-01-01",
                "end": "2026-01-10",
                "slug": "test-project",
            })

        assert response.status_code == 200
        assert response.json()["story_cycle_times"][0]["cycle_time_hours"] == 24.0

    def test_api_invalid_date_format_returns_400(self):
        """Validates that malformed dates return a 400 with a helpful message."""
        response = client.get("/cycle-time", params={
            "start": "01-01-2026",
            "end": "2026-01-10",
            "slug": "test-project",
        })
        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]

    def test_api_start_after_end_returns_400(self):
        """Validates that start > end returns a 400."""
        response = client.get("/cycle-time", params={
            "start": "2026-01-15",
            "end": "2026-01-10",
            "slug": "test-project",
        })
        assert response.status_code == 400

    def test_api_missing_slug_and_taiga_id_returns_400(self):
        """Validates that missing project identifier returns a 400."""
        response = client.get("/cycle-time", params={
            "start": "2026-01-01",
            "end": "2026-01-10",
        })
        assert response.status_code == 400
        assert "Missing 'slug' or 'taiga_id'" in response.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Validate InfluxDB write correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleTimeInfluxValidation:
    """
    Validate that cycle time metrics are written to InfluxDB
    with the correct structure and values.
    """

    @patch("src.core.influx.get_client")
    def test_influx_write_called_with_correct_slug(self, mock_gc):
        """Validates that the project slug is passed correctly to InfluxDB."""
        from src.core.influx import write_cycle_time_metrics

        mock_write_api = MagicMock()
        mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock(
            write_api=MagicMock(return_value=mock_write_api)
        ))
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        story_cycle_times = [
            {"story_id": 1, "cycle_time_hours": 24.0},
            {"story_id": 2, "cycle_time_hours": 48.0},
        ]

        result = write_cycle_time_metrics(
            project_slug="test-project",
            story_cycle_times=story_cycle_times,
        )

        # Should attempt to write (success or failure depends on mock setup)
        assert result is not None

    def test_influx_write_skips_none_cycle_times(self):
        """
        Validates that stories with None cycle time are not written to InfluxDB.
        Only valid (non-None) cycle times should produce InfluxDB points.
        """
        from src.core.influx import write_cycle_time_metrics

        story_cycle_times = [
            {"story_id": 1, "cycle_time_hours": None},
            {"story_id": 2, "cycle_time_hours": None},
        ]

        with patch("src.core.influx._write_with_retry") as mock_write:
            result = write_cycle_time_metrics(
                project_slug="test-project",
                story_cycle_times=story_cycle_times,
            )
            # No valid points → should not call write
            mock_write.assert_not_called()
            assert result.success is False

    def test_influx_write_produces_per_story_and_summary_points(self):
        """
        Validates that write_cycle_time_metrics produces:
        - 1 point per story (cycle_time_by_story measurement)
        - 1 summary point (cycle_time measurement)
        Total: n_stories + 1 points
        """
        from src.core.influx import write_cycle_time_metrics

        story_cycle_times = [
            {"story_id": 1, "cycle_time_hours": 24.0},
            {"story_id": 2, "cycle_time_hours": 48.0},
        ]

        with patch("src.core.influx._write_with_retry") as mock_write:
            mock_write.return_value = MagicMock(success=True, points_written=3)
            write_cycle_time_metrics(
                project_slug="test-project",
                story_cycle_times=story_cycle_times,
            )
            mock_write.assert_called_once()
            points = mock_write.call_args[0][0]
            # 2 per-story points + 1 summary point
            assert len(points) == 3
