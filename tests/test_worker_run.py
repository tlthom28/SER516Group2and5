"""Tests for src/worker/worker.py."""
from unittest.mock import patch, MagicMock


@patch("src.worker.worker.write_loc_metric")
@patch("src.worker.worker.time.sleep", side_effect=StopIteration)
def test_run_worker_writes_metric(mock_sleep, mock_write):
    from src.worker.worker import run_worker
    try:
        run_worker()
    except StopIteration:
        pass
    mock_write.assert_called_once()


@patch("src.worker.worker.write_loc_metric", side_effect=RuntimeError("no token"))
@patch("src.worker.worker.time.sleep", side_effect=StopIteration)
def test_run_worker_handles_error(mock_sleep, mock_write):
    from src.worker.worker import run_worker
    try:
        run_worker()
    except StopIteration:
        pass
    mock_write.assert_called_once()
