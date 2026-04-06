from unittest.mock import patch

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


class TestCycleTimeApi:
    @patch("src.api.routes.get_taiga_transition_history_data")
    def test_cycle_time_happy_path(self, mock_transition_history):
        mock_transition_history.return_value = {
            "status": "success",
            "project_id": 10,
            "project_slug": "demo-project",
            "sprint_id": 101,
            "stories": [
                {
                    "user_story_id": 1,
                    "transitions": [
                        {"to_status": "In Progress", "timestamp": "2026-03-01T10:00:00Z"},
                        {"to_status": "Done", "timestamp": "2026-03-03T10:00:00Z"},
                    ],
                }
            ],
        }

        response = client.get(
            "/cycle-time",
            params={
                "start": "2026-03-01",
                "end": "2026-03-10",
                "slug": "demo-project",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == 10
        assert data["project_slug"] == "demo-project"
        assert data["start_date"] == "2026-03-01"
        assert data["end_date"] == "2026-03-10"
        assert len(data["story_cycle_times"]) == 1
        assert data["story_cycle_times"][0]["story_id"] == 1
        assert data["story_cycle_times"][0]["cycle_time_hours"] == 48.0
        assert data["summary"]["average"] == 48.0

    def test_cycle_time_invalid_date_format(self):
        response = client.get(
            "/cycle-time",
            params={
                "start": "03-01-2026",
                "end": "2026-03-10",
                "slug": "demo-project",
            },
        )

        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]

    def test_cycle_time_start_after_end(self):
        response = client.get(
            "/cycle-time",
            params={
                "start": "2026-03-11",
                "end": "2026-03-10",
                "slug": "demo-project",
            },
        )

        assert response.status_code == 400
        assert "start" in response.json()["detail"]

    def test_cycle_time_requires_slug_or_taiga_id(self):
        response = client.get(
            "/cycle-time",
            params={
                "start": "2026-03-01",
                "end": "2026-03-10",
            },
        )

        assert response.status_code == 400
        assert "Missing 'slug' or 'taiga_id' parameter" in response.json()["detail"]

    @patch("src.api.routes.get_taiga_transition_history_data")
    def test_cycle_time_propagates_taiga_error(self, mock_transition_history):
        mock_transition_history.return_value = {
            "status": "error",
            "message": "Error: Invalid Taiga project id",
        }

        response = client.get(
            "/cycle-time",
            params={
                "start": "2026-03-01",
                "end": "2026-03-10",
                "slug": "bad-project",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"
        assert "Invalid Taiga project id" in data["message"]
