"""Tests for src/fill_dashboards.py helper functions."""
from unittest.mock import patch, MagicMock
from src.fill_dashboards import (
    wait_for_health,
    g2_class_coverage_run,
    g2_fog_index_run,
    g2_method_coverage_run,
    g2_taiga_metrics_run,
    g5_gh_metrics_run,
)


@patch("src.fill_dashboards.requests.get")
def test_wait_for_health_success(mock_get):
    mock_get.return_value = MagicMock(json=lambda: {"status": "healthy"})
    wait_for_health()
    mock_get.assert_called()


@patch("src.fill_dashboards.time.sleep")
@patch("src.fill_dashboards.requests.get")
def test_wait_for_health_timeout(mock_get, mock_sleep):
    import sys
    import requests as req
    mock_get.side_effect = req.exceptions.ConnectionError("conn refused")
    with patch.object(sys, "exit") as mock_exit:
        wait_for_health()
        mock_exit.assert_called_with(1)


@patch("src.fill_dashboards.requests.post")
def test_class_coverage_run(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    g2_class_coverage_run()
    mock_post.assert_called_once()


@patch("src.fill_dashboards.requests.post")
def test_fog_index_run(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    g2_fog_index_run()
    mock_post.assert_called_once()


@patch("src.fill_dashboards.requests.post")
def test_method_coverage_run(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    g2_method_coverage_run()
    mock_post.assert_called_once()


@patch("src.fill_dashboards.requests.post")
def test_g2_taiga_metrics_run(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    g2_taiga_metrics_run()
    mock_post.assert_called_once()


@patch("src.fill_dashboards.requests.post")
def test_g5_gh_metrics_run(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    g5_gh_metrics_run()
    mock_post.assert_called_once()
