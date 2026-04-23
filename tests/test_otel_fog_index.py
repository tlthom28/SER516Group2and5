import tempfile
import logging
from pathlib import Path
from src.services.fog_index import analyze_root
from unittest.mock import patch


class TestFogIndexLoggerExists:
    """Verify module-level logger is configured with canonical name."""
    def test_logger_name(self):
        import src.services.fog_index as mod
        assert hasattr(mod, "logger")
        assert mod.logger.name == "repopulse.services.fog_index"


class TestFogIndexLogging:
    """Verify fog index emits OTel-compatible structured logs."""
    def test_start_discovery_and_completion_logged(self, caplog):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "readable.py").write_text(
                '"""\n'
                "This module docstring contains enough words for fog analysis.\n"
                "It should produce a readable result with a stable score.\n"
                '"""\n'
            )

            with caplog.at_level(logging.INFO, logger="repopulse.services.fog_index"):
                result = analyze_root(
                    tmppath,
                    high_threshold=12.0,
                    low_threshold=5.0,
                    min_comment_words=5,
                    min_words=10,
                )

        assert len(result) == 1

        start_logs = [r for r in caplog.records if "Starting fog index analysis" in r.message]
        discovery_logs = [r for r in caplog.records if "Discovered files for fog index" in r.message]
        completion_logs = [r for r in caplog.records if "Fog index analysis complete" in r.message]

        assert len(start_logs) == 1
        assert len(discovery_logs) == 1
        assert "supported_files=1" in discovery_logs[0].message
        assert len(completion_logs) == 1
        assert "files=1" in completion_logs[0].message
        assert "scored=1" in completion_logs[0].message

    def test_per_file_summary_logged(self, caplog):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "short.py").write_text("# Hi there.\n")
            (tmppath / "documented.py").write_text(
                '"""\n'
                "This module docstring exists to exercise fog index logging.\n"
                "It includes enough words to avoid the short text path.\n"
                '"""\n'
            )

            with caplog.at_level(logging.INFO, logger="repopulse.services.fog_index"):
                result = analyze_root(
                    tmppath,
                    high_threshold=12.0,
                    low_threshold=5.0,
                    min_comment_words=5,
                    min_words=10,
                )

        assert len(result) == 2
        summary_logs = [r for r in caplog.records if "Fog index file summary" in r.message]
        detail_logs = [r for r in caplog.records if "Fog index file detail" in r.message]

        assert len(summary_logs) == 2
        assert any("file=short.py" in r.message and "status=ADD_MORE_TEXT" in r.message for r in summary_logs)
        assert any("file=documented.py" in r.message for r in summary_logs)
        assert any("file=short.py" in r.message for r in detail_logs)

    def test_read_error_logs_warning_and_summary(self, caplog):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "broken.py").write_text("# This file will fail to read.\n")

            with patch("pathlib.Path.read_text", side_effect=OSError("boom")):
                with caplog.at_level(logging.INFO, logger="repopulse.services.fog_index"):
                    result = analyze_root(
                        tmppath,
                        high_threshold=12.0,
                        low_threshold=5.0,
                        min_comment_words=5,
                        min_words=10,
                    )

        assert len(result) == 1
        assert result[0][1] == "READ_ERROR"

        warning_logs = [r for r in caplog.records if "Failed to read file for fog index" in r.message]
        completion_logs = [r for r in caplog.records if "Fog index analysis complete" in r.message]

        assert len(warning_logs) == 1
        assert "broken.py" in warning_logs[0].message
        assert len(completion_logs) == 1
        assert "read_errors=1" in completion_logs[0].message

