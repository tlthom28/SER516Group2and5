import os
import re
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

GITHUB_URL_PATTERN = re.compile(
    r"^https?://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+(\.git)?/?$"
)


class JobStatus(str, Enum):
    QUEUED = "queued"
    PENDING = "pending"
    PROCESSING = "processing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRequest(BaseModel):
    repo_url: Optional[str] = Field(default=None)
    local_path: Optional[str] = Field(default=None)

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v):
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("repo_url cannot be empty")
            if not GITHUB_URL_PATTERN.match(v):
                raise ValueError(
                    "repo_url must be a valid GitHub URL in the format "
                    "https://github.com/owner/repo"
                )
        return v

    @field_validator("local_path")
    @classmethod
    def validate_local_path(cls, v):
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("local_path cannot be empty")
            # Allow absolute paths on Windows and POSIX.
            # Also accept a leading '/' on Windows (tests use this form).
            if not (os.path.isabs(v) or v.startswith("/")):
                raise ValueError("local_path must be an absolute path")
            # Reject any '..' component in the raw path (before normalisation)
            if ".." in v:
                raise ValueError("local_path must not contain '..'")
        return v

    def model_post_init(self, __context):
        if not self.repo_url and not self.local_path:
            raise ValueError("Either 'repo_url' or 'local_path' must be provided")
        if self.repo_url and self.local_path:
            raise ValueError("Only one of 'repo_url' or 'local_path' should be provided, not both")


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    repo_url: Optional[str] = None
    local_path: Optional[str] = None
    created_at: str
    message: str


class JobDetailResponse(BaseModel):
    """Full job status including results (returned by GET /jobs/{job_id})."""
    job_id: str
    status: str
    progress: int = 0
    repo_url: Optional[str] = None
    local_path: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class WorkerHealthResponse(BaseModel):
    """Worker pool health info."""
    pool_size: int
    active_workers: int
    queued_jobs: int
    processing_jobs: int
    completed_jobs: int
    failed_jobs: int
    total_jobs: int


class CommitMetadata(BaseModel):
    """Git commit information linked to metric snapshots."""
    commit_hash: str = Field(..., description="Full commit SHA-1 hash")
    commit_timestamp: Optional[str] = Field(None, description="Commit timestamp (ISO 8601)")
    branch: str = Field(..., description="Branch name")
    author: Optional[str] = Field(None, description="Commit author")


class TimeSeriesMetricSnapshot(BaseModel):
    """Point-in-time metric snapshot linked to a Git commit."""
    repo_id: str = Field(..., description="Repository identifier")
    repo_name: str = Field(..., description="Repository name")
    commit_hash: str = Field(..., description="Git commit SHA-1 hash for metric linkage")
    commit_timestamp: Optional[str] = Field(None, description="Timestamp of commit (ISO 8601)")
    branch: str = Field(..., description="Branch name")
    snapshot_timestamp: str = Field(..., description="When snapshot was captured (ISO 8601)")
    granularity: str = Field(..., description="Snapshot granularity: 'project', 'package', or 'file'")
    snapshot_type: str = Field(default="loc", description="Type of metrics: 'loc' for lines of code")
    
    total_loc: int = Field(..., description="Total lines of code")
    code_loc: int = Field(..., description="Lines of actual code")
    comment_loc: int = Field(..., description="Lines of comments")
    blank_loc: int = Field(..., description="Blank lines")
    
    file_path: Optional[str] = Field(None, description="File path for file-level snapshots")
    package_name: Optional[str] = Field(None, description="Package name for package-level snapshots")
    language: Optional[str] = Field(None, description="Programming language")
    project_name: Optional[str] = Field(None, description="Project name if applicable")


class SnapshotData(BaseModel):
    total_loc: int = Field(..., description="Total LOC")
    code_loc: int = Field(..., description="Code LOC")
    comment_loc: int = Field(..., description="Comment LOC")
    blank_loc: int = Field(..., description="Blank lines")


class SnapshotRecord(BaseModel):
    timestamp: str = Field(..., description="Snapshot timestamp")
    repo_id: str = Field(..., description="Repository ID")
    repo_name: str = Field(..., description="Repository name")
    commit_hash: str = Field(..., description="Commit hash")
    branch: str = Field(..., description="Branch")
    granularity: str = Field(..., description="Granularity")
    metrics: SnapshotData = Field(..., description="Metrics")
    file_path: Optional[str] = Field(None, description="File path")
    package_name: Optional[str] = Field(None, description="Package name")


class SnapshotHistoryResponse(BaseModel):
    """Historical snapshots for a repository within a date range."""
    repo_id: str = Field(..., description="Repository ID")
    repo_name: str = Field(..., description="Repository name")
    granularity: str = Field(..., description="Granularity")
    start_time: str = Field(..., description="Range start")
    end_time: str = Field(..., description="Range end")
    snapshots: list[SnapshotRecord] = Field(..., description="Snapshots")
    count: int = Field(..., description="Count")


class LatestSnapshotResponse(BaseModel):
    """Latest snapshot for a repository."""
    repo_id: str = Field(..., description="Repository ID")
    repo_name: str = Field(..., description="Repository name")
    latest_snapshot: Optional[SnapshotRecord] = Field(None, description="Latest snapshot")


class CommitSnapshotsResponse(BaseModel):
    repo_id: str = Field(..., description="Repository ID")
    repo_name: str = Field(..., description="Repository name")
    commit_hash: str = Field(..., description="Commit hash")
    snapshots: list[SnapshotRecord] = Field(..., description="Snapshots")
    count: int = Field(..., description="Count")


class SnapshotQueryRequest(BaseModel):
    repo_id: str = Field(..., description="Repository ID")
    start_time: str = Field(..., description="Start timestamp")
    end_time: str = Field(..., description="End timestamp")
    granularity: Optional[str] = Field(None, description="Granularity filter")


class CommitInfo(BaseModel):
    """Commit information with timestamp and branch."""
    commit_hash: str = Field(..., description="Commit hash")
    branch: str = Field(..., description="Branch name")
    time: str = Field(..., description="Commit timestamp")


class CommitListResponse(BaseModel):
    """Commits in date range."""
    repo_id: str = Field(..., description="Repository ID")
    start_time: str = Field(..., description="Range start")
    end_time: str = Field(..., description="Range end")
    branch: Optional[str] = Field(None, description="Branch filter")
    commits: list[CommitInfo] = Field(..., description="Commits")
    count: int = Field(..., description="Count")


class CommitComparisonResponse(BaseModel):
    """Metrics comparison between two commits."""
    repo_id: str = Field(..., description="Repository ID")
    commit1: str = Field(..., description="First commit hash")
    commit2: str = Field(..., description="Second commit hash")
    granularity: str = Field(..., description="Granularity level")
    snapshots_commit1: list[dict] = Field(..., description="Snapshots from commit 1")
    snapshots_commit2: list[dict] = Field(..., description="Snapshots from commit 2")


class TrendPoint(BaseModel):
    """Single point in LOC trend."""
    time: str = Field(..., description="Timestamp")
    total_loc: int = Field(..., description="Total LOC")


class LocTrendResponse(BaseModel):
    """LOC values over time."""
    repo_id: str = Field(..., description="Repository ID")
    granularity: str = Field(..., description="Granularity level")
    start_time: str = Field(..., description="Range start")
    end_time: str = Field(..., description="Range end")
    trend: list[TrendPoint] = Field(..., description="Trend points")
    count: int = Field(..., description="Count")


class BranchMetrics(BaseModel):
    """Latest LOC for a branch."""
    branch: str = Field(..., description="Branch name")
    total_loc: int = Field(..., description="Total LOC")
    updated_at: str = Field(..., description="Latest update time")


class BranchMetricsResponse(BaseModel):
    """Latest LOC by branch."""
    repo_id: str = Field(..., description="Repository ID")
    branches: list[BranchMetrics] = Field(..., description="Branch metrics")
    count: int = Field(..., description="Count")


class LocChangeResponse(BaseModel):
    """LOC change data."""
    repo_id: str = Field(..., description="Repository ID")
    timestamp1: str = Field(..., description="Time 1")
    timestamp2: str = Field(..., description="Time 2")
    loc_at_time1: int = Field(..., description="LOC at time 1")
    loc_at_time2: int = Field(..., description="LOC at time 2")
    absolute_change: int = Field(..., description="Absolute change")
    percent_change: float = Field(..., description="Percent change")
    granularity: str = Field(..., description="Granularity")


# LOC Metrics Schema
class LOCMetrics(BaseModel):
    repo_id: str = Field(..., description="Unique identifier for the repository")
    repo_name: str = Field(..., description="Repository name")
    branch: str = Field(..., description="Branch name")
    commit_hash: Optional[str] = Field(None, description="Git commit hash for metric linkage")
    language: str = Field(..., description="Programming language")
    granularity: str = Field(..., description="Granularity of the metric: 'project', 'package', or 'file'")
    project_name: Optional[str] = Field(None, description="Project name if applicable")
    package_name: Optional[str] = Field(None, description="Package name if applicable")
    file_path: Optional[str] = Field(None, description="File path if applicable")
    total_loc: int = Field(..., description="Total lines of code")
    code_loc: int = Field(..., description="Lines of code (excluding comments and blanks)")
    comment_loc: int = Field(..., description="Lines of comments")
    blank_loc: int = Field(..., description="Blank lines")
    collected_at: str = Field(..., description="Timestamp when metrics were collected (ISO format)")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ErrorResponse(BaseModel):
    detail: str


class FileLOCResponse(BaseModel):
    path: str
    total_lines: int
    loc: int
    blank_lines: int
    excluded_lines: int
    comment_lines: int
    weighted_loc: float


class PackageLOCResponse(BaseModel):
    package: str
    loc: int
    file_count: int
    comment_lines: int
    weighted_loc: float
    files: list[FileLOCResponse]


class ModuleLOCResponse(BaseModel):
    module: str
    loc: int
    package_count: int
    file_count: int
    comment_lines: int
    packages: list[PackageLOCResponse]


class ProjectLOCResponse(BaseModel):
    project_root: str
    total_loc: int
    total_files: int
    total_blank_lines: int
    total_excluded_lines: int
    total_comment_lines: int
    total_weighted_loc: float
    packages: list[PackageLOCResponse]
    modules: list[ModuleLOCResponse]
    files: list[FileLOCResponse]


class LOCRequest(BaseModel):
    repo_path: str = Field(
        ..., description="Absolute path to the local repository to analyse"
    )

    @field_validator("repo_path")
    @classmethod
    def validate_repo_path(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("repo_path cannot be empty")
        # Allow absolute paths for the current OS.
        # Also accept paths that start with '/' on Windows.
        if not (os.path.isabs(v) or v.startswith("/")):
            raise ValueError("repo_path must be an absolute path")
        norm = os.path.normpath(v)
        if ".." in norm.split(os.path.sep):
            raise ValueError("repo_path must not contain '..'")
        return v


class AnalyzeRequest(BaseModel):
    """Request to clone and analyze a public GitHub repository."""
    repo_url: str = Field(..., description="Public GitHub HTTPS URL to analyse")
    start_date: Optional[str] = Field(None, description="Start date for the analysis in ISO format")
    end_date: Optional[str] = Field(None, description="End date for the analysis in ISO format")

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("repo_url cannot be empty")
        if not GITHUB_URL_PATTERN.match(v):
            raise ValueError(
                "repo_url must be a valid GitHub URL (e.g. https://github.com/owner/repo)"
            )
        return v


# WIP Metrics Schema


class WIPRequest(BaseModel):
    """Request body for POST /metrics/wip — compute WIP from a Taiga board."""
    taiga_url: Optional[str] = Field(
        None,
        description="Taiga scrum board URL (e.g., https://taiga.io/project/project-slug). "
                    "Computes user-story WIP per sprint."
    )
    kanban_url: Optional[str] = Field(
        None,
        description="Taiga kanban board URL (e.g., https://taiga.io/project/project-slug). "
                    "Computes task-level WIP over a date range. Takes priority if both are provided."
    )
    recent_days: Optional[int] = Field(
        None,
        description="For scrum: restrict to sprints ending within the last X days. "
                    "For kanban: date range window (defaults to 30 days)."
    )

    @field_validator("taiga_url")
    @classmethod
    def validate_taiga_url(cls, v):
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("taiga_url cannot be empty")
            if "/project/" not in v:
                raise ValueError(
                    "taiga_url must be a valid Taiga board URL in the format "
                    "https://taiga.io/project/project-slug"
                )
        return v

    @field_validator("kanban_url")
    @classmethod
    def validate_kanban_url(cls, v):
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("kanban_url cannot be empty")
            if "/project/" not in v:
                raise ValueError(
                    "kanban_url must be a valid Taiga board URL in the format "
                    "https://taiga.io/project/project-slug"
                )
        return v

    @field_validator("recent_days")
    @classmethod
    def validate_recent_days(cls, v):
        if v is not None:
            if not isinstance(v, int):
                raise ValueError("recent_days must be an integer")
            if v <= 0:
                raise ValueError("recent_days must be positive")
        return v

    def model_post_init(self, __context):
        if not self.taiga_url and not self.kanban_url:
            raise ValueError("Either 'taiga_url' or 'kanban_url' must be provided")


class DailyWIPMetricResponse(BaseModel):
    """Daily WIP metric for a single day."""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    wip_count: int = Field(..., description="Number of stories in WIP status")
    backlog_count: int = Field(..., description="Number of stories in backlog status")
    done_count: int = Field(..., description="Number of stories in done status")


class SprintWIPResponse(BaseModel):
    """WIP metrics for a single sprint."""
    project_id: int = Field(..., description="Taiga project ID")
    project_slug: str = Field(..., description="Taiga project slug")
    sprint_id: Optional[int] = Field(None, description="Taiga sprint/milestone ID (null for kanban)")
    sprint_name: str = Field(..., description="Name of the sprint")
    date_range_start: str = Field(..., description="Sprint start date (YYYY-MM-DD)")
    date_range_end: str = Field(..., description="Sprint end date (YYYY-MM-DD)")
    daily_wip: list[DailyWIPMetricResponse] = Field(..., description="Daily WIP data for each day in the sprint")


class WIPResponse(BaseModel):
    """Response for WIP metric calculation across all sprints."""
    project_id: int = Field(..., description="Taiga project ID")
    project_slug: str = Field(..., description="Taiga project slug")
    sprints_count: int = Field(..., description="Total number of sprints")
    sprints: list[SprintWIPResponse] = Field(..., description="WIP metrics for each sprint")


class ChurnResponse(BaseModel):
    """Churn metrics for a date range."""
    added: int
    deleted: int
    modified: int
    total: int


class AnalyzeResponse(BaseModel):
    """Full response for the /analyze endpoint including LOC and churn."""
    repo_url: str
    start_date: Optional[str] = Field(None, description="Start date for the analysis in ISO format")
    end_date: Optional[str] = Field(None, description="End date for the analysis in ISO format")
    loc: ProjectLOCResponse
    churn: Optional[ChurnResponse] = None
    churn_daily: Optional[dict[str, ChurnResponse]] = None


# --- Job Results models (GET /jobs/{job_id}/results) ---


class LOCResultSummary(BaseModel):
    """LOC metrics summary returned in job results."""
    total_loc: int
    total_files: int
    total_blank_lines: int
    total_excluded_lines: int
    total_comment_lines: int
    total_weighted_loc: float


class ChurnResultSummary(BaseModel):
    """Churn metrics summary returned in job results."""
    added: int
    deleted: int
    modified: int
    total: int


class ResultMetadata(BaseModel):
    """Metadata about a job result."""
    repository: str = Field(..., description="Repository URL or local path analysed")
    analysed_at: str = Field(..., description="ISO timestamp when the analysis completed")
    scope: str = Field(default="project", description="Granularity of the result")


class JobResultsResponse(BaseModel):
    """Structured metric results for a completed job."""
    job_id: str
    status: str
    metadata: ResultMetadata
    loc: LOCResultSummary
    churn: ChurnResultSummary


# Code Quality Metrics Models

class FogIndexFileResult(BaseModel):
    """Fog Index score for a single file."""
    score: Optional[float] = None
    status: str
    kind: str
    path: str
    message: str


class FogIndexMetricResponse(BaseModel):
    """Fog Index analysis results for a repository."""
    repository: str
    branch: str
    commit_sha: Optional[str] = None
    analyzed_at: str
    files: list[FogIndexFileResult]
    summary: dict = {}


class ClassCoverageFileResult(BaseModel):
    """Class coverage for a single file."""
    file_path: str
    total_classes: int
    documented_classes: int
    coverage_percent: float


class ClassCoverageMetricResponse(BaseModel):
    """Class comment coverage analysis results."""
    repository: str
    branch: str
    commit_sha: Optional[str] = None
    analyzed_at: str
    total_java_files: int
    total_classes: int
    documented_classes: int
    overall_coverage_percent: float
    files: list[ClassCoverageFileResult] = []


class MethodCoverageMetricResponse(BaseModel):
    """Method comment coverage analysis results."""
    repository: str
    branch: str
    commit_sha: Optional[str] = None
    analyzed_at: str
    public_coverage_percent: float
    protected_coverage_percent: float
    package_coverage_percent: float
    private_coverage_percent: float
    summary: dict = {}


class TaigaSprint(BaseModel):
    """Sprint metrics from Taiga."""
    sprint_id: int
    sprint_name: str
    adopted_work_count: int
    found_work_count: int = 0
    created_stories: int
    completed_stories: int


class TaigaMetricsResponse(BaseModel):
    """Taiga project metrics."""
    project_id: int
    project_slug: str
    analyzed_at: str
    sprints: list[TaigaSprint] = []

class CycleTimeStoryMetric(BaseModel):
    story_id: Optional[int] = None
    cycle_time_hours: Optional[float] = None

class CycleTimeSummary(BaseModel):
    average: Optional[float] = None
    median: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None

class CycleTimeResponse(BaseModel):
    project_id: int
    project_slug: str
    sprint_id: Optional[int] = None
    start_date: str
    end_date: str
    story_cycle_times: list[CycleTimeStoryMetric]
    summary: CycleTimeSummary
