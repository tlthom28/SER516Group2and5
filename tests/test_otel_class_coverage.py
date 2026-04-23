"""
US-186 / Task #196: OpenTelemetry implementation for class coverage.
"""
import logging
import tempfile
from pathlib import Path

from src.services.class_coverage import analyze_repo


class TestClassCoverageLoggerExists:
    """Verify module-level logger is configured with canonical name."""

    def test_logger_name(self):
        import src.services.class_coverage as mod

        assert hasattr(mod, "logger")
        assert mod.logger.name == "repopulse.services.class_coverage"


class TestClassCoverageLogging:
    """Verify class coverage service emits OTel-compatible structured logs."""

    def test_start_and_completion_summary_logged(self, caplog):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "Example.java").write_text(
                """
/**
 * Example class
 */
public class Example {}
""".strip()
            )

            with caplog.at_level(logging.INFO, logger="repopulse.services.class_coverage"):
                result = analyze_repo(
                    str(tmppath),
                    "test-user",
                    "test-repo",
                    "https://github.com/test-user/test-repo",
                    "main",
                    "abc123",
                )

        assert result["summary"]["total_classes_found"] == 1
        start_logs = [r for r in caplog.records if "Starting class coverage analysis" in r.message]
        completion_logs = [r for r in caplog.records if "Class coverage analysis complete" in r.message]
        assert len(start_logs) == 1
        assert len(completion_logs) == 1
        assert "test-repo" in completion_logs[0].message
        assert "coverage_pct=100.00" in completion_logs[0].message

    def test_discovery_and_file_summary_logged(self, caplog):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "DocA.java").write_text("/** Doc */\npublic class DocA {}")
            (tmppath / "NoDocB.java").write_text("public class NoDocB {}")

            with caplog.at_level(logging.INFO, logger="repopulse.services.class_coverage"):
                result = analyze_repo(
                    str(tmppath),
                    "owner",
                    "repo",
                    "url",
                    "main",
                    "sha",
                )

        assert result["summary"]["total_java_files_analyzed"] == 2

        discovery_logs = [r for r in caplog.records if "Discovered Java files for class coverage" in r.message]
        per_file_logs = [r for r in caplog.records if "Class coverage file summary" in r.message]

        assert len(discovery_logs) == 1
        assert "java_files=2" in discovery_logs[0].message
        assert len(per_file_logs) == 2

