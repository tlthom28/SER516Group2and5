"""
Tests for OpenTelemetry implementation of method coverage.
"""
import logging
import tempfile
from pathlib import Path

from src.services.method_coverage import scan_repo


class TestMethodCoverageLoggerExists:
    """Verify module-level logger is configured with canonical name."""

    def test_logger_name(self):
        import src.services.method_coverage as mod

        assert hasattr(mod, "logger")
        assert mod.logger.name == "repopulse.services.method_coverage"


class TestMethodCoverageLogging:
    """Verify method coverage service emits OTel-compatible structured logs."""

    def test_start_discovery_file_and_completion_logged(self, caplog):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "Example.java").write_text(
                """
public class Example {
    /** Doc */
    public void a() {}
    public void b() {}
}
""".strip()
            )

            with caplog.at_level(logging.INFO, logger="repopulse.services.method_coverage"):
                result = scan_repo(tmppath)

        assert result["public"]["total"] == 2
        assert result["public"]["documented"] == 1

        start_logs = [r for r in caplog.records if "Starting method coverage analysis" in r.message]
        discovery_logs = [r for r in caplog.records if "Discovered Java files for method coverage" in r.message]
        per_file_logs = [r for r in caplog.records if "Method coverage file summary" in r.message]
        completion_logs = [r for r in caplog.records if "Method coverage analysis complete" in r.message]

        assert len(start_logs) == 1
        assert len(discovery_logs) == 1
        assert len(per_file_logs) == 1
        assert len(completion_logs) == 1
