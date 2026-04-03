import pytest
from src.services.cycle_time import (
    compute_cycle_times,
    summarize_cycle_times
)

def _t(status, timestamp):
    return {"status": status, "timestamp": timestamp}

class TestComputeCycleTimesEdgeCases:

    def test_fractional_hours(self):
        stories = [{
            "story_id": 1,
            "transitions": [
                _t("In Progress", "2024-03-02T10:00:00"),
                _t("Done", "2024-03-02T10:30:00")
            ]
        }]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 0.5

    def test_iso_format_with_z_timezone(self):
        stories = [{
            "story_id": 1,
            "transitions": [
                _t("In Progress", "2024-03-02T10:00:00Z"),
                _t("Done", "2024-03-03T10:00:00Z")
            ]
        }]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] == 24.0

    def test_case_sensitive_status_matching(self):
        stories = [{
            "story_id": 1,
            "transitions": [
                _t("in progress", "2024-03-02T10:00:00"),
                _t("done", "2024-03-03T10:00:00")
            ]
        }]
        result = compute_cycle_times(stories)
        assert result[0]["cycle_time_hours"] is None




class TestSummarizeCycleTimesEdgeCases:

    def test_with_float_precision(self):
        results = [
            {"story_id": 1, "cycle_time_hours": 1.111111},
            {"story_id": 2, "cycle_time_hours": 2.222222},
            {"story_id": 3, "cycle_time_hours": 3.333333}
        ]
        result = summarize_cycle_times(results)
        assert result["average"] == pytest.approx(2.222222)
        assert result["median"] == pytest.approx(2.222222)

    def test_with_identical_values(self):
        results = [
            {"story_id": 1, "cycle_time_hours": 5.0},
            {"story_id": 2, "cycle_time_hours": 5.0},
            {"story_id": 3, "cycle_time_hours": 5.0}
        ]
        result = summarize_cycle_times(results)
        assert result["average"] == 5.0
        assert result["median"] == 5.0
        assert result["min"] == 5.0
        assert result["max"] == 5.0
