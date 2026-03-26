"""Tests for InfluxDB query functions and timeseries snapshot writer.

Covers the query helpers in src/core/influx.py that were previously untested,
bringing coverage above the 80% threshold.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from src.core.influx import (
    _parse_timestamp,
    write_timeseries_snapshot,
    query_flux,
    query_timeseries_snapshots_by_repo,
    query_latest_snapshot,
    query_snapshot_at_timestamp,
    query_snapshots_by_commit,
    query_commits_in_range,
    query_compare_commits,
    query_loc_trend,
    query_snapshots_by_granularity,
    query_current_loc_by_branch,
    query_loc_change_between,
)


# ---------------------------------------------------------------------------
# Helpers to build mock InfluxDB query results
# ---------------------------------------------------------------------------

def _mock_record(**kwargs):
    """Create a mock FluxRecord with get_time/get_value/get_field/values."""
    rec = MagicMock()
    rec.get_time.return_value = kwargs.get("time", datetime.now(timezone.utc))
    rec.get_value.return_value = kwargs.get("value", 100)
    rec.get_field.return_value = kwargs.get("field", "total_loc")
    rec.values = {
        "repo_id": kwargs.get("repo_id", "https://github.com/o/r"),
        "repo_name": kwargs.get("repo_name", "r"),
        "commit_hash": kwargs.get("commit_hash", "abc123"),
        "branch": kwargs.get("branch", "main"),
        "granularity": kwargs.get("granularity", "project"),
    }
    return rec


def _mock_table(records):
    """Wrap records in a mock FluxTable."""
    t = MagicMock()
    t.records = records
    return t


# =========================================================================
# _parse_timestamp
# =========================================================================

class TestParseTimestamp:
    def test_parses_iso_format(self):
        ts = _parse_timestamp("2026-01-15T10:00:00+00:00")
        assert ts is not None
        assert ts.year == 2026

    def test_parses_z_suffix(self):
        ts = _parse_timestamp("2026-01-15T10:00:00Z")
        assert ts is not None

    def test_returns_none_for_none(self):
        assert _parse_timestamp(None) is None

    def test_returns_none_for_empty(self):
        assert _parse_timestamp("") is None

    def test_returns_none_for_invalid(self):
        assert _parse_timestamp("not-a-date") is None


# =========================================================================
# write_timeseries_snapshot
# =========================================================================

class TestWriteTimeseriesSnapshot:
    @patch("src.core.influx.get_client")
    def test_writes_snapshot_successfully(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        write_timeseries_snapshot({
            "repo_id": "https://github.com/o/r",
            "repo_name": "r",
            "commit_hash": "abc123",
            "branch": "main",
            "granularity": "project",
            "snapshot_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_loc": 500,
            "code_loc": 400,
            "comment_loc": 50,
            "blank_loc": 50,
        })
        mock_write_api.write.assert_called_once()

    @patch("src.core.influx.get_client")
    def test_writes_with_optional_tags(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        write_timeseries_snapshot({
            "repo_id": "https://github.com/o/r",
            "repo_name": "r",
            "commit_hash": "abc123",
            "branch": "main",
            "granularity": "file",
            "snapshot_type": "loc",
            "file_path": "src/app.py",
            "language": "python",
            "total_loc": 100,
        })
        mock_write_api.write.assert_called_once()

    def test_raises_on_missing_required_tag(self):
        with pytest.raises(ValueError, match="Missing required tag"):
            write_timeseries_snapshot({
                "repo_id": "https://github.com/o/r",
                # missing repo_name, commit_hash, etc.
            })

    @patch("src.core.influx.get_client")
    def test_writes_with_no_timestamp_uses_utc_now(self, mock_get_client):
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        write_timeseries_snapshot({
            "repo_id": "https://github.com/o/r",
            "repo_name": "r",
            "commit_hash": "abc123",
            "branch": "main",
            "granularity": "project",
            # no snapshot_timestamp
            "total_loc": 100,
        })
        mock_write_api.write.assert_called_once()

    @patch("src.core.influx.get_client")
    def test_writes_with_non_numeric_falls_back(self, mock_get_client):
        """Non-numeric metric values should fall back to zeroes."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        write_timeseries_snapshot({
            "repo_id": "https://github.com/o/r",
            "repo_name": "r",
            "commit_hash": "abc123",
            "branch": "main",
            "granularity": "project",
            "total_loc": "not_a_number",
        })
        mock_write_api.write.assert_called_once()

    @patch("src.core.influx.get_client")
    def test_writes_with_metrics_subdict(self, mock_get_client):
        """When snapshot has a 'metrics' sub-dict, fields are read from it."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        write_timeseries_snapshot({
            "repo_id": "https://github.com/o/r",
            "repo_name": "r",
            "commit_hash": "abc123",
            "branch": "main",
            "granularity": "project",
            "metrics": {
                "total_loc": 999,
                "code_loc": 800,
                "comment_loc": 100,
                "blank_loc": 99,
            },
        })
        mock_write_api.write.assert_called_once()

    @patch("src.core.influx.get_client")
    def test_writes_with_invalid_timestamp(self, mock_get_client):
        """Invalid snapshot_timestamp should still write without timestamp."""
        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_get_client.return_value = mock_client

        write_timeseries_snapshot({
            "repo_id": "https://github.com/o/r",
            "repo_name": "r",
            "commit_hash": "abc123",
            "branch": "main",
            "granularity": "project",
            "snapshot_timestamp": "invalid-ts",
            "total_loc": 100,
        })
        mock_write_api.write.assert_called_once()


# =========================================================================
# query_flux
# =========================================================================

class TestQueryFlux:
    @patch("src.core.influx.get_client")
    def test_query_flux_calls_api(self, mock_get_client):
        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        mock_get_client.return_value = mock_client

        result = query_flux("from(bucket: \"test\")")
        mock_query_api.query.assert_called_once()
        assert result == []


# =========================================================================
# query_timeseries_snapshots_by_repo
# =========================================================================

class TestQuerySnapshots:
    @patch("src.core.influx.query_flux")
    def test_returns_snapshots(self, mock_qf):
        rec = _mock_record()
        mock_qf.return_value = [_mock_table([rec])]

        now = datetime.now(timezone.utc)
        result = query_timeseries_snapshots_by_repo("repo1", now - timedelta(days=7), now)
        assert len(result) == 1
        assert result[0]["repo_id"] == "https://github.com/o/r"

    @patch("src.core.influx.query_flux")
    def test_returns_empty_when_no_data(self, mock_qf):
        mock_qf.return_value = []
        now = datetime.now(timezone.utc)
        result = query_timeseries_snapshots_by_repo("repo1", now - timedelta(days=7), now)
        assert result == []

    @patch("src.core.influx.query_flux")
    def test_with_granularity_filter(self, mock_qf):
        mock_qf.return_value = []
        now = datetime.now(timezone.utc)
        query_timeseries_snapshots_by_repo("repo1", now - timedelta(days=7), now, granularity="file")
        mock_qf.assert_called_once()
        assert "file" in mock_qf.call_args[0][0]

    @patch("src.core.influx.query_flux")
    def test_multiple_tables(self, mock_qf):
        rec1 = _mock_record(value=10, commit_hash="aaa")
        rec2 = _mock_record(value=20, commit_hash="bbb")
        mock_qf.return_value = [_mock_table([rec1]), _mock_table([rec2])]

        now = datetime.now(timezone.utc)
        result = query_timeseries_snapshots_by_repo("repo1", now - timedelta(days=7), now)
        assert len(result) == 2


# =========================================================================
# query_latest_snapshot
# =========================================================================

class TestQueryLatestSnapshot:
    @patch("src.core.influx.query_flux")
    def test_returns_latest(self, mock_qf):
        rec = _mock_record(value=200)
        mock_qf.return_value = [_mock_table([rec])]

        result = query_latest_snapshot("repo1")
        assert result is not None
        assert result["value"] == 200

    @patch("src.core.influx.query_flux")
    def test_returns_none_when_empty(self, mock_qf):
        mock_qf.return_value = []
        assert query_latest_snapshot("repo1") is None

    @patch("src.core.influx.query_flux")
    def test_returns_none_when_no_records(self, mock_qf):
        mock_qf.return_value = [_mock_table([])]
        assert query_latest_snapshot("repo1") is None

    @patch("src.core.influx.query_flux")
    def test_with_custom_granularity(self, mock_qf):
        rec = _mock_record(granularity="file")
        mock_qf.return_value = [_mock_table([rec])]
        result = query_latest_snapshot("repo1", granularity="file")
        assert result is not None
        assert "file" in mock_qf.call_args[0][0]


# =========================================================================
# query_snapshot_at_timestamp
# =========================================================================

class TestQuerySnapshotAtTimestamp:
    @patch("src.core.influx.query_flux")
    def test_returns_snapshot(self, mock_qf):
        rec = _mock_record(value=150)
        mock_qf.return_value = [_mock_table([rec])]

        ts = datetime.now(timezone.utc)
        result = query_snapshot_at_timestamp("repo1", ts)
        assert result is not None
        assert result["value"] == 150

    @patch("src.core.influx.query_flux")
    def test_returns_none_when_empty(self, mock_qf):
        mock_qf.return_value = []
        ts = datetime.now(timezone.utc)
        assert query_snapshot_at_timestamp("repo1", ts) is None

    @patch("src.core.influx.query_flux")
    def test_returns_none_when_no_records(self, mock_qf):
        mock_qf.return_value = [_mock_table([])]
        ts = datetime.now(timezone.utc)
        assert query_snapshot_at_timestamp("repo1", ts) is None


# =========================================================================
# query_snapshots_by_commit
# =========================================================================

class TestQuerySnapshotsByCommit:
    @patch("src.core.influx.query_flux")
    def test_returns_snapshots(self, mock_qf):
        rec = _mock_record(commit_hash="abc123")
        mock_qf.return_value = [_mock_table([rec])]

        result = query_snapshots_by_commit("repo1", "abc123")
        assert len(result) == 1
        assert result[0]["commit_hash"] == "abc123"

    @patch("src.core.influx.query_flux")
    def test_empty_result(self, mock_qf):
        mock_qf.return_value = []
        assert query_snapshots_by_commit("repo1", "xyz") == []

    @patch("src.core.influx.query_flux")
    def test_multiple_records(self, mock_qf):
        rec1 = _mock_record(commit_hash="abc", field="total_loc", value=100)
        rec2 = _mock_record(commit_hash="abc", field="code_loc", value=80)
        mock_qf.return_value = [_mock_table([rec1, rec2])]

        result = query_snapshots_by_commit("repo1", "abc")
        assert len(result) == 2


# =========================================================================
# query_commits_in_range
# =========================================================================

class TestQueryCommitsInRange:
    @patch("src.core.influx.query_flux")
    def test_returns_commits(self, mock_qf):
        rec = _mock_record(commit_hash="abc123")
        mock_qf.return_value = [_mock_table([rec])]

        now = datetime.now(timezone.utc)
        result = query_commits_in_range("repo1", now - timedelta(days=30), now)
        assert len(result) == 1
        assert result[0]["commit_hash"] == "abc123"

    @patch("src.core.influx.query_flux")
    def test_with_branch_filter(self, mock_qf):
        mock_qf.return_value = []
        now = datetime.now(timezone.utc)
        query_commits_in_range("repo1", now - timedelta(days=30), now, branch="main")
        assert "main" in mock_qf.call_args[0][0]

    @patch("src.core.influx.query_flux")
    def test_deduplicates_commits(self, mock_qf):
        rec1 = _mock_record(commit_hash="abc123")
        rec2 = _mock_record(commit_hash="abc123")  # duplicate
        mock_qf.return_value = [_mock_table([rec1, rec2])]

        now = datetime.now(timezone.utc)
        result = query_commits_in_range("repo1", now - timedelta(days=30), now)
        assert len(result) == 1  # deduped

    @patch("src.core.influx.query_flux")
    def test_without_branch_filter(self, mock_qf):
        mock_qf.return_value = []
        now = datetime.now(timezone.utc)
        query_commits_in_range("repo1", now - timedelta(days=30), now)
        # No branch filter in query when branch is None
        query_str = mock_qf.call_args[0][0]
        assert 'r.branch ==' not in query_str

    @patch("src.core.influx.query_flux")
    def test_ignores_records_without_commit(self, mock_qf):
        rec = _mock_record(commit_hash="abc123")
        rec_no_commit = _mock_record()
        rec_no_commit.values["commit_hash"] = None
        mock_qf.return_value = [_mock_table([rec, rec_no_commit])]

        now = datetime.now(timezone.utc)
        result = query_commits_in_range("repo1", now - timedelta(days=30), now)
        assert len(result) == 1


# =========================================================================
# query_compare_commits
# =========================================================================

class TestQueryCompareCommits:
    @patch("src.core.influx.query_snapshots_by_commit")
    def test_compare_returns_both(self, mock_snap):
        mock_snap.side_effect = [
            [{"granularity": "project", "value": 100}],
            [{"granularity": "project", "value": 200}],
        ]
        result = query_compare_commits("repo1", "abc", "def")
        assert result["commit1"] == "abc"
        assert result["commit2"] == "def"
        assert len(result["snapshots_commit1"]) == 1
        assert len(result["snapshots_commit2"]) == 1

    @patch("src.core.influx.query_snapshots_by_commit")
    def test_compare_filters_by_granularity(self, mock_snap):
        mock_snap.side_effect = [
            [{"granularity": "project"}, {"granularity": "file"}],
            [{"granularity": "file"}],
        ]
        result = query_compare_commits("repo1", "a", "b", granularity="project")
        assert len(result["snapshots_commit1"]) == 1
        assert len(result["snapshots_commit2"]) == 0

    @patch("src.core.influx.query_snapshots_by_commit")
    def test_compare_empty_commits(self, mock_snap):
        mock_snap.side_effect = [[], []]
        result = query_compare_commits("repo1", "a", "b")
        assert result["snapshots_commit1"] == []
        assert result["snapshots_commit2"] == []


# =========================================================================
# query_loc_trend
# =========================================================================

class TestQueryLocTrend:
    @patch("src.core.influx.query_flux")
    def test_returns_trend(self, mock_qf):
        rec = _mock_record(value=500)
        mock_qf.return_value = [_mock_table([rec])]

        now = datetime.now(timezone.utc)
        result = query_loc_trend("repo1", now - timedelta(days=30), now)
        assert len(result) == 1
        assert result[0]["total_loc"] == 500

    @patch("src.core.influx.query_flux")
    def test_empty_trend(self, mock_qf):
        mock_qf.return_value = []
        now = datetime.now(timezone.utc)
        assert query_loc_trend("repo1", now - timedelta(days=30), now) == []

    @patch("src.core.influx.query_flux")
    def test_trend_multiple_points(self, mock_qf):
        rec1 = _mock_record(value=100)
        rec2 = _mock_record(value=200)
        rec3 = _mock_record(value=300)
        mock_qf.return_value = [_mock_table([rec1, rec2, rec3])]

        now = datetime.now(timezone.utc)
        result = query_loc_trend("repo1", now - timedelta(days=30), now)
        assert len(result) == 3
        assert [r["total_loc"] for r in result] == [100, 200, 300]


# =========================================================================
# query_snapshots_by_granularity
# =========================================================================

class TestQuerySnapshotsByGranularity:
    @patch("src.core.influx.query_flux")
    def test_returns_snapshots(self, mock_qf):
        rec = _mock_record(granularity="package")
        mock_qf.return_value = [_mock_table([rec])]

        result = query_snapshots_by_granularity("repo1", "package")
        assert len(result) == 1

    def test_invalid_granularity_returns_empty(self):
        result = query_snapshots_by_granularity("repo1", "invalid")
        assert result == []

    @patch("src.core.influx.query_flux")
    def test_accepts_file_granularity(self, mock_qf):
        mock_qf.return_value = []
        query_snapshots_by_granularity("repo1", "file", limit=50)
        assert "file" in mock_qf.call_args[0][0]

    @patch("src.core.influx.query_flux")
    def test_project_granularity(self, mock_qf):
        rec = _mock_record(granularity="project")
        mock_qf.return_value = [_mock_table([rec])]
        result = query_snapshots_by_granularity("repo1", "project")
        assert len(result) == 1
        assert result[0]["granularity"] == "project"

    @patch("src.core.influx.query_flux")
    def test_custom_limit(self, mock_qf):
        mock_qf.return_value = []
        query_snapshots_by_granularity("repo1", "project", limit=25)
        assert "25" in mock_qf.call_args[0][0]


# =========================================================================
# query_current_loc_by_branch
# =========================================================================

class TestQueryCurrentLocByBranch:
    @patch("src.core.influx.query_flux")
    def test_returns_branches(self, mock_qf):
        rec = _mock_record(branch="main", value=1000)
        mock_qf.return_value = [_mock_table([rec])]

        result = query_current_loc_by_branch("repo1")
        assert len(result) == 1
        assert result[0]["branch"] == "main"
        assert result[0]["total_loc"] == 1000

    @patch("src.core.influx.query_flux")
    def test_empty_result(self, mock_qf):
        mock_qf.return_value = []
        assert query_current_loc_by_branch("repo1") == []

    @patch("src.core.influx.query_flux")
    def test_multiple_branches(self, mock_qf):
        rec1 = _mock_record(branch="main", value=1000)
        rec2 = _mock_record(branch="develop", value=1200)
        mock_qf.return_value = [_mock_table([rec1]), _mock_table([rec2])]

        result = query_current_loc_by_branch("repo1")
        assert len(result) == 2
        branches = {r["branch"] for r in result}
        assert branches == {"main", "develop"}


# =========================================================================
# query_loc_change_between
# =========================================================================

class TestQueryLocChangeBetween:
    @patch("src.core.influx.query_snapshot_at_timestamp")
    def test_returns_zero_when_no_snapshots(self, mock_snap):
        mock_snap.return_value = None
        now = datetime.now(timezone.utc)
        result = query_loc_change_between("repo1", now - timedelta(days=7), now)
        assert result["absolute_change"] == 0
        assert result["percent_change"] == 0
        assert result["loc_at_time1"] == 0
        assert result["loc_at_time2"] == 0

    @patch("src.core.influx.query_snapshot_at_timestamp")
    def test_returns_change_with_table_like_snapshots(self, mock_snap):
        """When snapshots are returned as table-like iterables, loc values are extracted."""
        rec1 = _mock_record(field="total_loc", value=100)
        rec2 = _mock_record(field="total_loc", value=200)
        table1 = _mock_table([rec1])
        table2 = _mock_table([rec2])

        # query_loc_change_between iterates snap as tables: for table in snap: for record in table.records
        mock_snap.side_effect = [[table1], [table2]]

        now = datetime.now(timezone.utc)
        result = query_loc_change_between("repo1", now - timedelta(days=7), now)
        assert result["loc_at_time1"] == 100
        assert result["loc_at_time2"] == 200
        assert result["absolute_change"] == 100
        assert result["percent_change"] == 100.0

    @patch("src.core.influx.query_snapshot_at_timestamp")
    def test_returns_zero_change_when_same(self, mock_snap):
        rec = _mock_record(field="total_loc", value=500)
        table = _mock_table([rec])
        mock_snap.side_effect = [[table], [table]]

        now = datetime.now(timezone.utc)
        result = query_loc_change_between("repo1", now - timedelta(days=7), now)
        assert result["absolute_change"] == 0
        assert result["percent_change"] == 0

    @patch("src.core.influx.query_snapshot_at_timestamp")
    def test_only_first_snapshot_available(self, mock_snap):
        rec = _mock_record(field="total_loc", value=100)
        table = _mock_table([rec])
        mock_snap.side_effect = [[table], None]

        now = datetime.now(timezone.utc)
        result = query_loc_change_between("repo1", now - timedelta(days=7), now)
        # loc1=100, loc2=0 → change = 0 because condition is `if (loc1 and loc2)`
        assert result["loc_at_time1"] == 100
        assert result["loc_at_time2"] == 0

    @patch("src.core.influx.query_snapshot_at_timestamp")
    def test_result_contains_expected_keys(self, mock_snap):
        mock_snap.return_value = None
        now = datetime.now(timezone.utc)
        result = query_loc_change_between("repo1", now - timedelta(days=7), now)
        expected_keys = {
            "repo_id", "timestamp1", "timestamp2",
            "loc_at_time1", "loc_at_time2",
            "absolute_change", "percent_change", "granularity",
        }
        assert set(result.keys()) == expected_keys
