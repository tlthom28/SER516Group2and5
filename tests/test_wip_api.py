from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.main import app


client = TestClient(app)


class TestWipApiPersistence:
    @patch("src.api.routes.write_wip_metrics")
    @patch("src.api.routes.calculate_kanban_wip")
    def test_wip_kanban_persists_metrics(self, mock_calc_kanban, mock_write_wip):
        mock_calc_kanban.return_value = SimpleNamespace(
            project_id=10,
            project_slug="demo-project",
            date_range_start="2026-03-01",
            date_range_end="2026-03-03",
            daily_wip=[
                SimpleNamespace(date="2026-03-01", wip_count=3, backlog_count=2, done_count=1),
                SimpleNamespace(date="2026-03-02", wip_count=4, backlog_count=1, done_count=2),
            ],
        )

        response = client.post(
            "/metrics/wip",
            json={"kanban_url": "https://taiga.io/project/demo-project", "recent_days": 7},
        )

        assert response.status_code == 200
        mock_write_wip.assert_called_once()

        # write_wip_metrics is called with a dict as positional argument
        call_args = mock_write_wip.call_args.args[0]
        assert call_args["project_slug"] == "demo-project"
        assert len(call_args["sprints"]) == 1
        assert call_args["sprints"][0]["sprint_name"] == "kanban"
        assert len(call_args["sprints"][0]["daily_wip"]) == 2

    @patch("src.api.routes.write_wip_metrics")
    @patch("src.api.routes.calculate_daily_wip_all_sprints")
    def test_wip_scrum_persists_metrics(self, mock_calc_scrum, mock_write_wip):
        mock_calc_scrum.return_value = [
            SimpleNamespace(
                project_id=20,
                project_slug="team-space",
                sprint_id=1,
                sprint_name="Sprint 1",
                date_range_start="2026-03-01",
                date_range_end="2026-03-07",
                daily_wip=[
                    SimpleNamespace(date="2026-03-01", wip_count=2, backlog_count=3, done_count=1)
                ],
            ),
            SimpleNamespace(
                project_id=20,
                project_slug="team-space",
                sprint_id=2,
                sprint_name="Sprint 2",
                date_range_start="2026-03-08",
                date_range_end="2026-03-14",
                daily_wip=[
                    SimpleNamespace(date="2026-03-08", wip_count=1, backlog_count=2, done_count=4)
                ],
            ),
        ]

        response = client.post(
            "/metrics/wip",
            json={"taiga_url": "https://taiga.io/project/team-space", "recent_days": 30},
        )

        assert response.status_code == 200
        mock_write_wip.assert_called_once()

        # write_wip_metrics is called with a dict as positional argument
        call_args = mock_write_wip.call_args.args[0]
        assert call_args["project_slug"] == "team-space"
        assert len(call_args["sprints"]) == 2

    @patch("src.api.routes.write_wip_metrics", side_effect=RuntimeError("influx unavailable"))
    @patch("src.api.routes.calculate_kanban_wip")
    def test_wip_write_failure_does_not_fail_response(self, mock_calc_kanban, _mock_write_wip):
        mock_calc_kanban.return_value = SimpleNamespace(
            project_id=10,
            project_slug="demo-project",
            date_range_start="2026-03-01",
            date_range_end="2026-03-03",
            daily_wip=[
                SimpleNamespace(date="2026-03-01", wip_count=3, backlog_count=2, done_count=1),
            ],
        )

        response = client.post(
            "/metrics/wip",
            json={"kanban_url": "https://taiga.io/project/demo-project"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["project_slug"] == "demo-project"
        assert data["sprints_count"] == 1
