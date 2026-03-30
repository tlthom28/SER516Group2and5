import pytest
from src.services.cycle_time import compute_cycle_times, validate_cycle_time_input, summarize_cycle_times


def _t(status, timestamp):
    return {"status": status, "timestamp": timestamp}


class TestComputeCycleTimes:

    def test_single_story_in_progress_to_done(self):
        stories = [{"story_id": 1, "transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
            _t("Done", "2024-01-11T10:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert len(results) == 1
        assert results[0]["story_id"] == 1
        assert results[0]["cycle_time_hours"] == 24.0

    def test_cycle_time_is_calculated_in_hours(self):
        stories = [{"story_id": 1, "transitions": [
            _t("In Progress", "2024-01-10T08:00:00+00:00"),
            _t("Done", "2024-01-10T14:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert results[0]["cycle_time_hours"] == 6.0

    def test_multiple_stories(self):
        stories = [
            {"story_id": 1, "transitions": [
                _t("In Progress", "2024-01-10T10:00:00+00:00"),
                _t("Done", "2024-01-11T10:00:00+00:00"),
            ]},
            {"story_id": 2, "transitions": [
                _t("In Progress", "2024-01-10T10:00:00+00:00"),
                _t("Done", "2024-01-12T10:00:00+00:00"),
            ]},
        ]
        results = compute_cycle_times(stories)
        assert len(results) == 2
        assert results[0]["cycle_time_hours"] == 24.0
        assert results[1]["cycle_time_hours"] == 48.0

    def test_transitions_sorted_by_timestamp(self):
        stories = [{"story_id": 1, "transitions": [
            _t("Done", "2024-01-12T10:00:00+00:00"),
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert results[0]["cycle_time_hours"] == 48.0

    def test_story_with_intermediate_states(self):
        stories = [{"story_id": 1, "transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
            _t("Review", "2024-01-11T10:00:00+00:00"),
            _t("Done", "2024-01-13T10:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert results[0]["cycle_time_hours"] == 72.0

    def test_empty_transitions_returns_none(self):
        stories = [{"story_id": 1, "transitions": []}]
        results = compute_cycle_times(stories)
        assert len(results) == 1
        assert results[0]["story_id"] == 1
        assert results[0]["cycle_time_hours"] is None

    def test_missing_transitions_key_returns_none(self):
        stories = [{"story_id": 1}]
        results = compute_cycle_times(stories)
        assert len(results) == 1
        assert results[0]["cycle_time_hours"] is None

    def test_no_in_progress_returns_none(self):
        stories = [{"story_id": 1, "transitions": [
            _t("Ready", "2024-01-10T10:00:00+00:00"),
            _t("Done", "2024-01-11T10:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert results[0]["cycle_time_hours"] is None

    def test_no_done_returns_none(self):
        stories = [{"story_id": 1, "transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert results[0]["cycle_time_hours"] is None

    def test_empty_story_list(self):
        results = compute_cycle_times([])
        assert results == []

    def test_reopened_item_uses_last_done(self):
        stories = [{"story_id": 1, "transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
            _t("Done", "2024-01-12T10:00:00+00:00"),
            _t("In Progress", "2024-01-13T10:00:00+00:00"),
            _t("Done", "2024-01-15T10:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert results[0]["cycle_time_hours"] == 120.0

    def test_mixed_valid_and_invalid_stories(self):
        stories = [
            {"story_id": 1, "transitions": [
                _t("In Progress", "2024-01-10T10:00:00+00:00"),
                _t("Done", "2024-01-11T10:00:00+00:00"),
            ]},
            {"story_id": 2, "transitions": [
                _t("In Progress", "2024-01-10T10:00:00+00:00"),
            ]},
            {"story_id": 3, "transitions": []},
        ]
        results = compute_cycle_times(stories)
        assert len(results) == 3
        assert results[0]["cycle_time_hours"] == 24.0
        assert results[1]["cycle_time_hours"] is None
        assert results[2]["cycle_time_hours"] is None

    def test_story_id_preserved_in_result(self):
        stories = [{"story_id": 999, "transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
            _t("Done", "2024-01-11T10:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert results[0]["story_id"] == 999

    def test_story_id_none_when_missing(self):
        stories = [{"transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
            _t("Done", "2024-01-11T10:00:00+00:00"),
        ]}]
        results = compute_cycle_times(stories)
        assert results[0]["story_id"] is None
        assert results[0]["cycle_time_hours"] == 24.0


class TestValidateCycleTimeInput:

    def test_valid_story(self):
        story = {"transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
            _t("Done", "2024-01-11T10:00:00+00:00"),
        ]}
        assert validate_cycle_time_input(story) is True

    def test_not_a_dict(self):
        assert validate_cycle_time_input("not a dict") is False
        assert validate_cycle_time_input(123) is False
        assert validate_cycle_time_input(None) is False

    def test_missing_transitions_key(self):
        assert validate_cycle_time_input({"story_id": 1}) is False

    def test_transitions_not_a_list(self):
        assert validate_cycle_time_input({"transitions": "bad"}) is False

    def test_empty_transitions(self):
        assert validate_cycle_time_input({"transitions": []}) is False

    def test_transition_missing_status(self):
        story = {"transitions": [{"timestamp": "2024-01-10T10:00:00+00:00"}]}
        assert validate_cycle_time_input(story) is False

    def test_transition_missing_timestamp(self):
        story = {"transitions": [{"status": "Done"}]}
        assert validate_cycle_time_input(story) is False

    def test_single_valid_transition(self):
        story = {"transitions": [_t("In Progress", "2024-01-10T10:00:00+00:00")]}
        assert validate_cycle_time_input(story) is True

    def test_multiple_transitions_all_valid(self):
        story = {"transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
            _t("Review", "2024-01-11T10:00:00+00:00"),
            _t("Done", "2024-01-12T10:00:00+00:00"),
        ]}
        assert validate_cycle_time_input(story) is True

    def test_one_bad_transition_fails_all(self):
        story = {"transitions": [
            _t("In Progress", "2024-01-10T10:00:00+00:00"),
            {"status": "Done"},
        ]}
        assert validate_cycle_time_input(story) is False


class TestSummarizeCycleTimes:

    def test_single_result(self):
        results = [{"story_id": 1, "cycle_time_hours": 24.0}]
        summary = summarize_cycle_times(results)
        assert summary["average"] == 24.0
        assert summary["median"] == 24.0
        assert summary["min"] == 24.0
        assert summary["max"] == 24.0

    def test_two_results(self):
        results = [
            {"story_id": 1, "cycle_time_hours": 10.0},
            {"story_id": 2, "cycle_time_hours": 30.0},
        ]
        summary = summarize_cycle_times(results)
        assert summary["average"] == 20.0
        assert summary["median"] == 20.0
        assert summary["min"] == 10.0
        assert summary["max"] == 30.0

    def test_three_results_odd_count_median(self):
        results = [
            {"story_id": 1, "cycle_time_hours": 10.0},
            {"story_id": 2, "cycle_time_hours": 20.0},
            {"story_id": 3, "cycle_time_hours": 60.0},
        ]
        summary = summarize_cycle_times(results)
        assert summary["average"] == 30.0
        assert summary["median"] == 20.0
        assert summary["min"] == 10.0
        assert summary["max"] == 60.0

    def test_none_values_are_excluded(self):
        results = [
            {"story_id": 1, "cycle_time_hours": 24.0},
            {"story_id": 2, "cycle_time_hours": None},
            {"story_id": 3, "cycle_time_hours": 48.0},
        ]
        summary = summarize_cycle_times(results)
        assert summary["average"] == 36.0
        assert summary["min"] == 24.0
        assert summary["max"] == 48.0

    def test_all_none_results(self):
        results = [
            {"story_id": 1, "cycle_time_hours": None},
            {"story_id": 2, "cycle_time_hours": None},
        ]
        summary = summarize_cycle_times(results)
        assert summary["average"] is None
        assert summary["median"] is None
        assert summary["min"] is None
        assert summary["max"] is None

    def test_empty_list(self):
        summary = summarize_cycle_times([])
        assert summary["average"] is None
        assert summary["median"] is None
        assert summary["min"] is None
        assert summary["max"] is None
