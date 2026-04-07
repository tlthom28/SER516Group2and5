"""InfluxDB write pipeline with batch optimisation, retry logic, and write confirmation."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from src.core.config import Config

logger = logging.getLogger("repopulse.influx")

_client: Optional[InfluxDBClient] = None

# -- Configurable pipeline knobs --
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.5          # seconds — doubles each attempt
BATCH_SIZE = 500                   # flush every N points


# ---------------------------------------------------------------------------
# Write result model — returned by every write function for confirmation
# ---------------------------------------------------------------------------

@dataclass
class WriteResult:
    """Acknowledgment returned after a write (or batch write) attempt."""
    success: bool
    points_written: int = 0
    points_failed: int = 0
    errors: list[str] = field(default_factory=list)
    retries_used: int = 0


# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

def get_client() -> InfluxDBClient:
    global _client
    if _client is None:
        if not Config.INFLUX_TOKEN:
            raise RuntimeError("INFLUX_TOKEN not configured")
        _client = InfluxDBClient(
            url=Config.INFLUX_URL,
            token=Config.INFLUX_TOKEN,
            org=Config.INFLUX_ORG,
        )
    return _client


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _parse_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 timestamp or return None."""
    if not ts_str:
        return None
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except (ValueError, AttributeError):
        logger.warning(f"Failed to parse timestamp: {ts_str}")
        return None


def _build_loc_point(loc_metric: dict) -> Point:
    """Convert a LOC metric dict to an InfluxDB Point."""
    p = Point("loc_metrics")
    
    for tag in ("repo_id", "repo_name", "branch", "language", "granularity",
                "project_name", "package_name", "file_path", "commit_hash"):
        v = loc_metric.get(tag)
        if v is not None:
            p = p.tag(tag, str(v))

    try:
        p = p.field("total_loc", int(loc_metric.get("total_loc", 0)))
        p = p.field("code_loc", int(loc_metric.get("code_loc", 0)))
        p = p.field("comment_loc", int(loc_metric.get("comment_loc", 0)))
        p = p.field("blank_loc", int(loc_metric.get("blank_loc", 0)))
    except (ValueError, TypeError):
        logger.warning(f"Non-numeric metric values, using defaults: {loc_metric}")
        p = p.field("total_loc", 0).field("code_loc", 0).field("comment_loc", 0).field("blank_loc", 0)

    ts = loc_metric.get("collected_at")
    if ts:
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            p = p.time(t, WritePrecision.NS)
        except Exception:
            pass
    return p


def write_timeseries_snapshot(snapshot: dict) -> None:
    """Write time-series metric snapshot linked to commit."""
    client = get_client()
    write_api = client.write_api(write_options=SYNCHRONOUS)

    p = Point("timeseries_snapshot")
    
    required_tags = ("repo_id", "repo_name", "commit_hash", "branch", "granularity")
    for tag in required_tags:
        v = snapshot.get(tag)
        if v is None:
            raise ValueError(f"Missing required tag for snapshot: {tag}")
        p = p.tag(tag, str(v))
    
    for tag in ("snapshot_type", "file_path", "package_name", "language"):
        v = snapshot.get(tag)
        if v is not None:
            p = p.tag(tag, str(v))

    metrics = snapshot.get("metrics") or snapshot
    try:
        p = p.field("total_loc", int(metrics.get("total_loc", 0)))
        p = p.field("code_loc", int(metrics.get("code_loc", 0)))
        p = p.field("comment_loc", int(metrics.get("comment_loc", 0)))
        p = p.field("blank_loc", int(metrics.get("blank_loc", 0)))
    except (ValueError, TypeError):
        logger.warning(f"Non-numeric snapshot metrics: {snapshot}")
        p = p.field("total_loc", 0).field("code_loc", 0).field("comment_loc", 0).field("blank_loc", 0)

    snapshot_ts = snapshot.get("snapshot_timestamp")
    if snapshot_ts:
        ts = _parse_timestamp(snapshot_ts)
        if ts:
            p = p.time(ts, WritePrecision.NS)
    else:
        p = p.time(datetime.now(timezone.utc), WritePrecision.NS)

    write_api.write(bucket=Config.INFLUX_BUCKET, org=Config.INFLUX_ORG, record=p)
    logger.debug(f"Wrote time-series snapshot: {snapshot.get('repo_name')} @ commit {snapshot.get('commit_hash', '')[:8]}")

def _write_with_retry(points: list[Point], max_retries: int = MAX_RETRIES) -> WriteResult:
    """Write a list of points with exponential-backoff retry.

    Returns a ``WriteResult`` with confirmation details.
    """
    client = get_client()
    write_api = client.write_api(write_options=SYNCHRONOUS)

    result = WriteResult(success=False)
    attempt = 0

    while attempt <= max_retries:
        try:
            write_api.write(
                bucket=Config.INFLUX_BUCKET,
                org=Config.INFLUX_ORG,
                record=points,
            )
            result.success = True
            result.points_written = len(points)
            result.retries_used = attempt
            return result
        except Exception as exc:
            attempt += 1
            result.errors.append(f"attempt {attempt}/{max_retries + 1}: {exc}")
            if attempt <= max_retries:
                backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    f"InfluxDB write failed (attempt {attempt}), retrying in {backoff:.1f}s: {exc}"
                )
                time.sleep(backoff)

    # all retries exhausted
    result.points_failed = len(points)
    result.retries_used = max_retries
    logger.error(f"InfluxDB write failed after {max_retries + 1} attempts: {result.errors[-1]}")
    return result


# ---------------------------------------------------------------------------
# Public write functions
# ---------------------------------------------------------------------------

def write_loc_metric(loc_metric: dict) -> WriteResult:
    """Write a single LOC metric point with retry. Returns WriteResult."""
    point = _build_loc_point(loc_metric)
    return _write_with_retry([point])


def batch_write_loc_metrics(metrics: list[dict]) -> WriteResult:
    """Write many LOC metrics in batches for performance.

    Points are flushed in chunks of ``BATCH_SIZE``.  Each chunk is retried
    independently so a transient failure doesn't discard the whole payload.

    Returns an aggregate ``WriteResult`` with totals.
    """
    if not metrics:
        return WriteResult(success=True)

    points = [_build_loc_point(m) for m in metrics]

    aggregate = WriteResult(success=True)

    # chunk the points into batches
    for i in range(0, len(points), BATCH_SIZE):
        chunk = points[i : i + BATCH_SIZE]
        chunk_result = _write_with_retry(chunk)
        aggregate.points_written += chunk_result.points_written
        aggregate.points_failed += chunk_result.points_failed
        aggregate.errors.extend(chunk_result.errors)
        aggregate.retries_used = max(aggregate.retries_used, chunk_result.retries_used)
        if not chunk_result.success:
            aggregate.success = False

    logger.info(
        f"Batch write complete: {aggregate.points_written} written, "
        f"{aggregate.points_failed} failed, {aggregate.retries_used} max retries"
    )
    return aggregate


def write_churn_metric(repo_url: str, start_date: str, end_date: str, churn: dict) -> WriteResult:
    """Write a single churn summary point with retry."""
    point = (
        Point("repo_churn")
        .tag("repo_url", repo_url)
        .tag("start_date", start_date)
        .tag("end_date", end_date)
        .field("added", churn["added"])
        .field("deleted", churn["deleted"])
        .field("modified", churn["modified"])
        .field("total", churn["total"])
    )
    return _write_with_retry([point])


def write_daily_churn_metrics(repo_url: str, daily: dict[str, dict[str, int]]) -> WriteResult:
    """Write daily churn points as a batch with retry."""
    points: list[Point] = []
    for date_str, churn in daily.items():
        ts = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
        point = (
            Point("repo_churn_daily")
            .tag("repo_url", repo_url)
            .field("added", churn["added"])
            .field("deleted", churn["deleted"])
            .field("modified", churn["modified"])
            .field("total", churn["total"])
            .time(ts, WritePrecision.NS)
        )
        points.append(point)

    if not points:
        return WriteResult(success=True)

    return _write_with_retry(points)


# ---------------------------------------------------------------------------
# Query helper
# ---------------------------------------------------------------------------

def query_flux(query: str):
    """Execute a Flux query against InfluxDB."""
    client = get_client()
    query_api = client.query_api()
    return query_api.query(org=Config.INFLUX_ORG, query=query)


def query_timeseries_snapshots_by_repo(
    repo_id: str,
    start_time: datetime,
    end_time: datetime,
    granularity: Optional[str] = None
) -> list[dict]:
    start_iso = start_time.isoformat()
    end_iso = end_time.isoformat()
    granularity_filter = f'|> filter(fn: (r) => r.granularity == "{granularity}")' if granularity else ""
    
    flux_query = f'''
    from(bucket: "{Config.INFLUX_BUCKET}")
      |> range(start: {start_iso}, stop: {end_iso})
      |> filter(fn: (r) => r._measurement == "timeseries_snapshot")
      |> filter(fn: (r) => r.repo_id == "{repo_id}")
      {granularity_filter}
      |> sort(columns: ["_time"], desc: true)
    '''
    
    results = query_flux(flux_query)
    snapshots = []
    for table in results:
        for record in table.records:
            snapshots.append({
                "time": record.get_time(),
                "repo_id": record.values.get("repo_id"),
                "repo_name": record.values.get("repo_name"),
                "commit_hash": record.values.get("commit_hash"),
                "branch": record.values.get("branch"),
                "granularity": record.values.get("granularity"),
                "value": record.get_value(),
                "field": record.get_field(),
            })
    return snapshots


def query_latest_snapshot(
    repo_id: str,
    granularity: str = "project"
) -> Optional[dict]:
    flux_query = f'''
    from(bucket: "{Config.INFLUX_BUCKET}")
      |> range(start: -30d)
      |> filter(fn: (r) => r._measurement == "timeseries_snapshot")
      |> filter(fn: (r) => r.repo_id == "{repo_id}")
      |> filter(fn: (r) => r.granularity == "{granularity}")
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: 1)
    '''
    
    results = query_flux(flux_query)
    if not results or not results[0].records:
        return None
    
    record = results[0].records[0]
    return {
        "time": record.get_time(),
        "repo_id": record.values.get("repo_id"),
        "repo_name": record.values.get("repo_name"),
        "commit_hash": record.values.get("commit_hash"),
        "branch": record.values.get("branch"),
        "granularity": record.values.get("granularity"),
        "value": record.get_value(),
        "field": record.get_field(),
    }


def query_snapshot_at_timestamp(
    repo_id: str,
    timestamp: datetime,
    granularity: str = "project"
) -> Optional[dict]:
    end_iso = timestamp.isoformat()
    start_iso = (timestamp - __import__("datetime").timedelta(days=30)).isoformat()
    
    flux_query = f'''
    from(bucket: "{Config.INFLUX_BUCKET}")
      |> range(start: {start_iso}, stop: {end_iso})
      |> filter(fn: (r) => r._measurement == "timeseries_snapshot")
      |> filter(fn: (r) => r.repo_id == "{repo_id}")
      |> filter(fn: (r) => r.granularity == "{granularity}")
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: 1)
    '''
    
    results = query_flux(flux_query)
    if not results or not results[0].records:
        return None
    
    record = results[0].records[0]
    return {
        "time": record.get_time(),
        "repo_id": record.values.get("repo_id"),
        "repo_name": record.values.get("repo_name"),
        "commit_hash": record.values.get("commit_hash"),
        "branch": record.values.get("branch"),
        "granularity": record.values.get("granularity"),
        "value": record.get_value(),
        "field": record.get_field(),
    }


def query_snapshots_by_commit(
    repo_id: str,
    commit_hash: str
) -> list[dict]:
    flux_query = f'''
    from(bucket: "{Config.INFLUX_BUCKET}")
      |> range(start: -90d)
      |> filter(fn: (r) => r._measurement == "timeseries_snapshot")
      |> filter(fn: (r) => r.repo_id == "{repo_id}")
      |> filter(fn: (r) => r.commit_hash == "{commit_hash}")
      |> sort(columns: ["_time"], desc: true)
    '''
    
    results = query_flux(flux_query)
    snapshots = []
    for table in results:
        for record in table.records:
            snapshots.append({
                "time": record.get_time(),
                "repo_id": record.values.get("repo_id"),
                "repo_name": record.values.get("repo_name"),
                "commit_hash": record.values.get("commit_hash"),
                "branch": record.values.get("branch"),
                "granularity": record.values.get("granularity"),
                "value": record.get_value(),
                "field": record.get_field(),
            })
    return snapshots


def query_commits_in_range(
    repo_id: str,
    start_time: datetime,
    end_time: datetime,
    branch: Optional[str] = None
) -> list[dict]:
    """Get commits with snapshots in date range."""
    start_iso = start_time.isoformat()
    end_iso = end_time.isoformat()
    
    branch_filter = f'r.branch == "{branch}" and' if branch else ""
    
    flux_query = f'''
    from(bucket: "{Config.INFLUX_BUCKET}")
      |> range(start: {start_iso}, stop: {end_iso})
      |> filter(fn: (r) => r._measurement == "timeseries_snapshot")
      |> filter(fn: (r) => r.repo_id == "{repo_id}")
      |> filter(fn: (r) => {branch_filter} r._field == "total_loc")
      |> group(columns: ["commit_hash"])
      |> sort(columns: ["_time"], desc: true)
    '''
    
    results = query_flux(flux_query)
    commits = []
    seen = set()
    
    for table in results:
        for record in table.records:
            commit = record.values.get("commit_hash")
            if commit and commit not in seen:
                commits.append({
                    "commit_hash": commit,
                    "repo_id": record.values.get("repo_id"),
                    "branch": record.values.get("branch"),
                    "time": record.get_time(),
                })
                seen.add(commit)
    return commits


def query_compare_commits(
    repo_id: str,
    commit1: str,
    commit2: str,
    granularity: str = "project"
) -> dict:
    """Compare metrics between two commits."""
    snap1 = query_snapshots_by_commit(repo_id, commit1)
    snap2 = query_snapshots_by_commit(repo_id, commit2)
    
    snap1_filtered = [s for s in snap1 if s.get("granularity") == granularity]
    snap2_filtered = [s for s in snap2 if s.get("granularity") == granularity]
    
    return {
        "repo_id": repo_id,
        "commit1": commit1,
        "commit2": commit2,
        "granularity": granularity,
        "snapshots_commit1": snap1_filtered,
        "snapshots_commit2": snap2_filtered,
    }


def query_loc_trend(
    repo_id: str,
    start_time: datetime,
    end_time: datetime,
    granularity: str = "project"
) -> list[dict]:
    """Get LOC trend over time."""
    start_iso = start_time.isoformat()
    end_iso = end_time.isoformat()
    
    flux_query = f'''
    from(bucket: "{Config.INFLUX_BUCKET}")
      |> range(start: {start_iso}, stop: {end_iso})
      |> filter(fn: (r) => r._measurement == "timeseries_snapshot")
      |> filter(fn: (r) => r.repo_id == "{repo_id}")
      |> filter(fn: (r) => r.granularity == "{granularity}")
      |> filter(fn: (r) => r._field == "total_loc")
      |> sort(columns: ["_time"])
    '''
    
    results = query_flux(flux_query)
    trend = []
    
    for table in results:
        for record in table.records:
            trend.append({
                "time": record.get_time(),
                "repo_id": record.values.get("repo_id"),
                "total_loc": record.get_value(),
                "granularity": granularity,
            })
    return trend


def query_snapshots_by_granularity(
    repo_id: str,
    granularity: str,
    limit: int = 100
) -> list[dict]:
    """Get snapshots at granularity level."""
    if granularity not in ("project", "package", "file"):
        return []
    
    flux_query = f'''
    from(bucket: "{Config.INFLUX_BUCKET}")
      |> range(start: -90d)
      |> filter(fn: (r) => r._measurement == "timeseries_snapshot")
      |> filter(fn: (r) => r.repo_id == "{repo_id}")
      |> filter(fn: (r) => r.granularity == "{granularity}")
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: {limit})
    '''
    
    results = query_flux(flux_query)
    snapshots = []
    
    for table in results:
        for record in table.records:
            snapshots.append({
                "time": record.get_time(),
                "repo_id": record.values.get("repo_id"),
                "granularity": record.values.get("granularity"),
                "commit_hash": record.values.get("commit_hash"),
                "value": record.get_value(),
                "field": record.get_field(),
            })
    return snapshots


def query_current_loc_by_branch(repo_id: str) -> list[dict]:
    """Get latest LOC per branch."""
    flux_query = f'''
    from(bucket: "{Config.INFLUX_BUCKET}")
      |> range(start: -90d)
      |> filter(fn: (r) => r._measurement == "timeseries_snapshot")
      |> filter(fn: (r) => r.repo_id == "{repo_id}")
      |> filter(fn: (r) => r.granularity == "project")
      |> group(columns: ["branch"])
      |> sort(columns: ["_time"], desc: true)
      |> first()
    '''
    
    results = query_flux(flux_query)
    branches = []
    
    for table in results:
        for record in table.records:
            branches.append({
                "branch": record.values.get("branch"),
                "time": record.get_time(),
                "total_loc": record.get_value(),
                "repo_id": record.values.get("repo_id"),
            })
    return branches


def query_loc_change_between(
    repo_id: str,
    ts1: datetime,
    ts2: datetime,
    granularity: str = "project"
) -> dict:
    """Calculate LOC change between two times."""
    snap1 = query_snapshot_at_timestamp(repo_id, ts1, granularity)
    snap2 = query_snapshot_at_timestamp(repo_id, ts2, granularity)
    
    loc1 = 0
    loc2 = 0
    
    if snap1:
        for table in snap1:
            for record in table.records:
                if record.get_field() == "total_loc":
                    loc1 = record.get_value()
                    break
    
    if snap2:
        for table in snap2:
            for record in table.records:
                if record.get_field() == "total_loc":
                    loc2 = record.get_value()
                    break
    
    change = loc2 - loc1 if (loc1 and loc2) else 0
    percent_change = (change / loc1 * 100) if loc1 else 0
    
    
    return {
        "repo_id": repo_id,
        "timestamp1": ts1.isoformat(),
        "timestamp2": ts2.isoformat(),
        "loc_at_time1": loc1,
        "loc_at_time2": loc2,
        "absolute_change": change,
        "percent_change": round(percent_change, 2),
        "granularity": granularity,
    }


# ---------------------------------------------------------------------------
# Code Quality Metrics Write Functions
# ---------------------------------------------------------------------------

def write_fog_index_metrics(
    repo_name: str,
    branch: str,
    files_results: list[tuple],
    commit_sha: str = "",
) -> WriteResult:
    """Write Fog Index metrics to InfluxDB.
    
    Args:
        repo_name: Repository name/ID
        branch: Branch name
        files_results: List of tuples (score, status, kind, path, message)
        commit_sha: Optional commit SHA
    
    Returns:
        WriteResult with success/failure info
    """
    points = []
    for score, status, kind, path, message in files_results:
        try:
            p = (
                Point("fog_index_score")
                .tag("repo_name", repo_name)
                .tag("branch", branch)
                .tag("file_kind", kind)
                .tag("file_path", str(path))
                .tag("status", status)
            )
            if commit_sha:
                p = p.tag("commit_hash", commit_sha)
            
            if score is not None:
                p = p.field("score", float(score))
            p = p.field("message", message or "")
            p = p.time(datetime.now(timezone.utc), WritePrecision.NS)
            
            points.append(p)
        except Exception as e:
            logger.warning(f"Failed to build fog index point for {path}: {e}")
    
    if not points:
        return WriteResult(success=False, errors=["No valid points to write"])
    
    return _write_with_retry(points)


def write_class_coverage_metrics(
    repo_name: str,
    branch: str,
    total_classes: int,
    documented_classes: int,
    coverage_percent: float,
    commit_sha: str = "",
    files_detail: list[dict] = None,
) -> WriteResult:
    """Write class comment coverage metrics to InfluxDB.
    
    Args:
        repo_name: Repository name/ID
        branch: Branch name
        total_classes: Total classes found
        documented_classes: Classes with JavaDoc
        coverage_percent: Coverage percentage
        commit_sha: Optional commit SHA
        files_detail: Optional list of per-file coverage details
    
    Returns:
        WriteResult with success/failure info
    """
    points = []
    
    # Summary point
    summary_point = (
        Point("class_coverage")
        .tag("repo_name", repo_name)
        .tag("branch", branch)
        .field("total_classes", int(total_classes))
        .field("documented_classes", int(documented_classes))
        .field("coverage_percent", float(coverage_percent))
    )
    if commit_sha:
        summary_point = summary_point.tag("commit_hash", commit_sha)
    summary_point = summary_point.time(datetime.now(timezone.utc), WritePrecision.NS)
    points.append(summary_point)
    
    # Per-file details if provided
    if files_detail:
        for file_info in files_detail:
            try:
                file_point = (
                    Point("class_coverage_by_file")
                    .tag("repo_name", repo_name)
                    .tag("branch", branch)
                    .tag("file_path", file_info.get("file_path", ""))
                    .field("total_classes", int(file_info.get("total_classes", 0)))
                    .field("documented_classes", int(file_info.get("documented_classes", 0)))
                    .field("coverage_percent", float(file_info.get("coverage_percent", 0)))
                )
                if commit_sha:
                    file_point = file_point.tag("commit_hash", commit_sha)
                file_point = file_point.time(datetime.now(timezone.utc), WritePrecision.NS)
                points.append(file_point)
            except Exception as e:
                logger.warning(f"Failed to build class coverage point for file: {e}")
    
    if not points:
        return WriteResult(success=False, errors=["No valid points to write"])
    
    return _write_with_retry(points)


def write_method_coverage_metrics(
    repo_name: str,
    branch: str,
    public_coverage: float,
    protected_coverage: float,
    package_coverage: float,
    private_coverage: float,
    commit_sha: str = "",
) -> WriteResult:
    """Write method comment coverage metrics to InfluxDB.
    
    Args:
        repo_name: Repository name/ID
        branch: Branch name
        public_coverage: Public method coverage %
        protected_coverage: Protected method coverage %
        package_coverage: Package-private method coverage %
        private_coverage: Private method coverage %
        commit_sha: Optional commit SHA
    
    Returns:
        WriteResult with success/failure info
    """
    points = []
    
    for visibility, coverage in [
        ("public", public_coverage),
        ("protected", protected_coverage),
        ("package", package_coverage),
        ("private", private_coverage),
    ]:
        try:
            p = (
                Point("method_coverage")
                .tag("repo_name", repo_name)
                .tag("branch", branch)
                .tag("visibility", visibility)
                .field("coverage_percent", float(coverage))
            )
            if commit_sha:
                p = p.tag("commit_hash", commit_sha)
            p = p.time(datetime.now(timezone.utc), WritePrecision.NS)
            points.append(p)
        except Exception as e:
            logger.warning(f"Failed to build method coverage point for {visibility}: {e}")
    
    if not points:
        return WriteResult(success=False, errors=["No valid points to write"])
    
    return _write_with_retry(points)


def write_taiga_metrics(
    project_slug: str,
    sprints_data: list[dict],
    cycle_time_data: Optional[list[dict]] = None,
) -> WriteResult:
    """Write Taiga sprint metrics to InfluxDB.
    
    Args:
        project_slug: Taiga project slug
        sprints_data: List of sprint metric dicts with sprint_id, sprint_name, adopted_work_count, etc.
        cycle_time_data: Optional per-story cycle time metrics.
    
    Returns:
        WriteResult with success/failure info
    """
    points = []
    
    for sprint in sprints_data:
        try:
            p = (
                Point("taiga_adopted_work")
                .tag("project_slug", project_slug)
                .tag("sprint_id", str(sprint.get("sprint_id", "")))
                .tag("sprint_name", sprint.get("sprint_name", ""))
                .field("adopted_work_count", int(sprint.get("adopted_work_count", 0)))
                .field("created_stories", int(sprint.get("created_stories", 0)))
                .field("completed_stories", int(sprint.get("completed_stories", 0)))
            )
            p = p.time(datetime.now(timezone.utc), WritePrecision.NS)
            points.append(p)
        except Exception as e:
            logger.warning(f"Failed to build taiga metrics point: {e}")

    for story in cycle_time_data or []:
        cycle_time_hours = story.get("cycle_time_hours")
        if cycle_time_hours is None:
            continue

        try:
            p = (
                Point("taiga_cycle_time")
                .tag("project_slug", project_slug)
                .tag("user_story_id", str(story.get("user_story_id", "")))
                .field("cycle_time_hours", float(cycle_time_hours))
                .field("cycle_time_days", float(cycle_time_hours) / 24.0)
            )

            story_name = story.get("user_story_name")
            if story_name:
                p = p.tag("user_story_name", str(story_name))

            end_timestamp = _parse_timestamp(story.get("end_timestamp"))
            if end_timestamp:
                p = p.time(end_timestamp, WritePrecision.NS)
            else:
                p = p.time(datetime.now(timezone.utc), WritePrecision.NS)

            points.append(p)
        except Exception as e:
            logger.warning(f"Failed to build taiga cycle time point: {e}")
    
    if not points:
        return WriteResult(success=False, errors=["No valid points to write"])
    
    return _write_with_retry(points)


# file: map_wip_response_to_points for transforming WIP API response to InfluxDB points
def map_wip_response_to_points(wip_response: dict) -> list:

    points = []
    
    project_id = wip_response.get("project_id")
    project_slug = wip_response.get("project_slug")
    sprints = wip_response.get("sprints", [])
    
    if not sprints:
        logger.warning("No sprints in WIP response")
        return points
    
    for sprint in sprints:
        sprint_id = sprint.get("sprint_id")
        sprint_name = sprint.get("sprint_name", "")
        daily_wip = sprint.get("daily_wip", [])
        
        if not daily_wip:
            logger.debug(f"No daily WIP data for sprint {sprint_id}")
            continue
        
        for day in daily_wip:
            date_str = day.get("date")
            wip_count = day.get("wip_count", 0)
            backlog_count = day.get("backlog_count", 0)
            done_count = day.get("done_count", 0)
            
            if not date_str:
                continue
            
            try:
                time_obj = datetime.fromisoformat(date_str)
                p = (
                    Point("taiga_wip")
                    .tag("project_id", str(project_id))
                    .tag("project_slug", str(project_slug))
                    .tag("sprint_id", str(sprint_id))
                    .tag("sprint_name", sprint_name)
                    .field("wip_count", int(wip_count))
                    .field("backlog_count", int(backlog_count))
                    .field("done_count", int(done_count))
                    .time(time_obj, WritePrecision.NS)
                )
                points.append(p)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse WIP point for {date_str}: {e}")
                continue
    
    return points




