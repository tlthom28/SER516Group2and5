import logging
import os
import uuid
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.api.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChurnResponse,
    ChurnResultSummary,
    HealthResponse,
    JobDetailResponse,
    JobRequest,
    JobResponse,
    JobResultsResponse,
    JobStatus,
    LOCRequest,
    LOCResultSummary,
    ProjectLOCResponse,
    PackageLOCResponse,
    ModuleLOCResponse,
    FileLOCResponse,
    ResultMetadata,
    WorkerHealthResponse,
    WIPRequest,
    WIPResponse,
    TimeSeriesMetricSnapshot,
    SnapshotHistoryResponse,
    LatestSnapshotResponse,
    CommitSnapshotsResponse,
    SnapshotRecord,
    SnapshotData,
    CommitInfo,
    CommitListResponse,
    CommitComparisonResponse,
    LocTrendResponse,
    BranchMetricsResponse,
    BranchMetrics,
    LocChangeResponse,
    FogIndexMetricResponse,
    ClassCoverageMetricResponse,
    MethodCoverageMetricResponse,
    TaigaMetricsResponse,
    CycleTimeResponse,
)
from src.metrics.loc import count_loc_in_directory
from src.metrics.churn import compute_daily_churn
from src.core.influx import (
    get_client,
    write_loc_metric,
    write_churn_metric,
    write_daily_churn_metrics,
    write_fog_index_metrics,
    write_class_coverage_metrics,
    write_method_coverage_metrics,
    write_taiga_metrics,
    write_wip_metrics,
    write_cycle_time_metrics,
    _parse_timestamp,
    query_latest_snapshot,
    query_timeseries_snapshots_by_repo,
    query_snapshot_at_timestamp,
    query_snapshots_by_commit,
    query_commits_in_range,
    query_compare_commits,
    query_loc_trend,
    query_current_loc_by_branch,
    query_loc_change_between,
)
from src.core.git_clone import GitRepoCloner, GitCloneError
from src.metrics.wip import calculate_kanban_wip, calculate_daily_wip_all_sprints, TaigaFetchError

logger = logging.getLogger("repopulse")

router = APIRouter()


@router.get("/")
async def read_root():
    return {"message": "Welcome to RepoPulse API"}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        service="RepoPulse API",
        version="1.0.0",
    )


@router.get("/health/db")
async def db_health():
    """Check connectivity to InfluxDB using the client health endpoint."""
    try:
        client = get_client()
        health = client.health()
        status = getattr(health, "status", None) or (health.get("status") if isinstance(health, dict) else "unknown")
        message = getattr(health, "message", None) or (health.get("message") if isinstance(health, dict) else "")
        return {"status": status, "message": message}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "detail": str(e)})


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(request: Request):
    """Submit a repo analysis job to the worker pool."""
    body = await request.json()
    logger.info(f"Incoming job request: {body}")

    try:
        job_request = JobRequest(**body)
    except ValidationError as e:
        errors = e.errors()
        messages = [err["msg"] for err in errors]
        logger.warning(f"Validation failed: {messages}")
        return JSONResponse(
            status_code=400,
            content={"detail": messages},
        )

    job_id = str(uuid.uuid4())

    # submit to the worker pool
    pool = request.app.state.worker_pool
    try:
        pool.submit(
            job_id=job_id,
            repo_url=job_request.repo_url,
            local_path=job_request.local_path,
        )
    except RuntimeError as e:
        return JSONResponse(status_code=503, content={"detail": str(e)})

    created_at = datetime.now(timezone.utc).isoformat()

    job = JobResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        repo_url=job_request.repo_url,
        local_path=job_request.local_path,
        created_at=created_at,
        message="Job queued for processing",
    )
    logger.info(f"Job queued: {job_id}")
    return job


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str, request: Request):
    """Get the current status and result of a job."""
    pool = request.app.state.worker_pool
    record = pool.get_job(job_id)
    if record is None:
        return JSONResponse(status_code=404, content={"detail": "Job not found"})
    return JobDetailResponse(**record.to_dict())


@router.get("/jobs/{job_id}/results", response_model=JobResultsResponse)
async def get_job_results(job_id: str, request: Request):
    """Retrieve the formatted metric results (LOC + Churn) for a completed job.

    Results are cached in the worker pool's in-memory job store,
    so repeated calls return instantly without re-computation.
    """
    pool = request.app.state.worker_pool
    record = pool.get_job(job_id)

    if record is None:
        return JSONResponse(status_code=404, content={"detail": "Job not found"})

    if record.status != "completed":
        return JSONResponse(
            status_code=200,
            content={
                "job_id": record.job_id,
                "status": record.status,
                "message": f"Job is {record.status}. Results are not available yet.",
            },
        )

    result = record.result or {}
    churn = result.get("churn", {})

    metadata = ResultMetadata(
        repository=record.repo_url or record.local_path or "unknown",
        analysed_at=record.completed_at or "",
        scope="project",
    )

    loc_summary = LOCResultSummary(
        total_loc=result.get("total_loc", 0),
        total_files=result.get("total_files", 0),
        total_blank_lines=result.get("total_blank_lines", 0),
        total_excluded_lines=result.get("total_excluded_lines", 0),
        total_comment_lines=result.get("total_comment_lines", 0),
        total_weighted_loc=result.get("total_weighted_loc", 0.0),
    )

    churn_summary = ChurnResultSummary(
        added=churn.get("added", 0),
        deleted=churn.get("deleted", 0),
        modified=churn.get("modified", 0),
        total=churn.get("total", 0),
    )

    return JobResultsResponse(
        job_id=record.job_id,
        status=record.status,
        metadata=metadata,
        loc=loc_summary,
        churn=churn_summary,
    )


@router.get("/jobs", response_model=list[JobDetailResponse])
async def list_jobs(request: Request):
    """List all jobs with their statuses."""
    pool = request.app.state.worker_pool
    return [JobDetailResponse(**j) for j in pool.list_jobs()]


@router.get("/workers/health", response_model=WorkerHealthResponse)
async def workers_health(request: Request):
    """Return worker pool health: pool size, active/queued/completed counts."""
    pool = request.app.state.worker_pool
    return WorkerHealthResponse(**pool.health())


# --- LOC Metric Endpoint ---


@router.post("/metrics/loc", response_model=ProjectLOCResponse, status_code=200)
async def compute_loc(request: Request):
    """Compute LOC for a local repo path. Supports .java, .py, and .ts files."""
    body = await request.json()
    logger.info(f"LOC metric request: {body}")

    try:
        loc_request = LOCRequest(**body)
    except ValidationError as e:
        errors = e.errors()
        messages = [err["msg"] for err in errors]
        logger.warning(f"LOC validation failed: {messages}")
        return JSONResponse(
            status_code=400,
            content={"detail": messages},
        )

    repo_path = loc_request.repo_path

    if not os.path.isdir(repo_path):
        logger.warning(f"LOC path not found: {repo_path}")
        return JSONResponse(
            status_code=404,
            content={"detail": f"Directory not found: {repo_path}"},
        )

    project_loc = count_loc_in_directory(repo_path)

    return ProjectLOCResponse(
        project_root=project_loc.project_root,
        total_loc=project_loc.total_loc,
        total_files=project_loc.total_files,
        total_blank_lines=project_loc.total_blank_lines,
        total_excluded_lines=project_loc.total_excluded_lines,
        total_comment_lines=project_loc.total_comment_lines,
        total_weighted_loc=project_loc.total_weighted_loc,
        packages=[
            PackageLOCResponse(
                package=pkg.package,
                loc=pkg.loc,
                file_count=pkg.file_count,
                comment_lines=pkg.comment_lines,
                weighted_loc=pkg.weighted_loc,
                files=[
                    FileLOCResponse(
                        path=f.path,
                        total_lines=f.total_lines,
                        loc=f.loc,
                        blank_lines=f.blank_lines,
                        excluded_lines=f.excluded_lines,
                        comment_lines=f.comment_lines,
                        weighted_loc=f.weighted_loc,
                    )
                    for f in pkg.files
                ],
            )
            for pkg in project_loc.packages
        ],
        modules=[
            ModuleLOCResponse(
                module=m.module,
                loc=m.loc,
                package_count=len(m.packages),
                file_count=m.file_count,
                comment_lines=m.comment_lines,
                packages=[
                    PackageLOCResponse(
                        package=p.package,
                        loc=p.loc,
                        file_count=p.file_count,
                        comment_lines=p.comment_lines,
                        weighted_loc=p.weighted_loc,
                        files=[
                            FileLOCResponse(
                                path=f.path,
                                total_lines=f.total_lines,
                                loc=f.loc,
                                blank_lines=f.blank_lines,
                                excluded_lines=f.excluded_lines,
                                comment_lines=f.comment_lines,
                                weighted_loc=f.weighted_loc,
                            )
                            for f in p.files
                        ],
                    )
                    for p in m.packages
                ],
            )
            for m in project_loc.modules
        ],
        files=[
            FileLOCResponse(
                path=f.path,
                total_lines=f.total_lines,
                loc=f.loc,
                blank_lines=f.blank_lines,
                excluded_lines=f.excluded_lines,
                comment_lines=f.comment_lines,
                weighted_loc=f.weighted_loc,
            )
            for f in project_loc.files
        ],
    )

@router.post("/analyze", response_model=AnalyzeResponse, status_code=200)
async def analyze_repo(request: Request):
    """Clone a public GitHub repo, compute LOC and churn metrics, write to InfluxDB, and return results."""
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        return JSONResponse(status_code=400, content={"detail": f"Invalid JSON body: {e}"})
    logger.info(f"Analyze request: {body}")

    try:
        analyze_request = AnalyzeRequest(**body)
    except ValidationError as e:
        errors = e.errors()
        messages = [err["msg"] for err in errors]
        logger.warning(f"Analyze validation failed: {messages}")
        return JSONResponse(status_code=400, content={"detail": messages})

    repo_url = analyze_request.repo_url

    today = datetime.now(timezone.utc).date()
    end_date = analyze_request.end_date or today.isoformat()
    start_date = analyze_request.start_date or (today - timedelta(days=7)).isoformat()

    cloner = GitRepoCloner()

    try:
        logger.info(f"Cloning {repo_url} (shallow clone, then deepen for churn)")
        repo_path = cloner.clone(repo_url, shallow=True)
        logger.info(f"Clone complete: {repo_path}")

        cloner.deepen_since(repo_path, start_date)

        project_loc = count_loc_in_directory(repo_path)

        logger.info(f"Computing daily churn for {start_date} to {end_date}")
        daily = compute_daily_churn(repo_path, start_date, end_date)
        logger.info(f"Daily churn: {len(daily)} days with activity")

        churn_summary = {"added": 0, "deleted": 0, "modified": 0, "total": 0}
        for day_churn in daily.values():
            churn_summary["added"] += day_churn["added"]
            churn_summary["deleted"] += day_churn["deleted"]
        churn_summary["modified"] = min(churn_summary["added"], churn_summary["deleted"])
        churn_summary["total"] = churn_summary["added"] + churn_summary["deleted"]

        repo_name = repo_url.rstrip("/").rstrip(".git").split("/")[-1]
        commit_hash = cloner.commit_hash
        commit_timestamp = GitRepoCloner.get_commit_timestamp(repo_path, commit_hash)
        logger.info(f"Repository at commit {commit_hash[:8] if commit_hash else 'unknown'}")

        try:
            loc_payload = {
                "repo_id": repo_name,
                "repo_name": repo_name,
                "branch": "main",
                "language": "mixed",
                "granularity": "project",
                "total_loc": project_loc.total_loc,
                "code_loc": project_loc.total_loc,
                "comment_loc": project_loc.total_comment_lines,
                "blank_loc": project_loc.total_blank_lines,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
            write_loc_metric(loc_payload)
        except Exception as influx_err:
            logger.warning(f"Failed to write metrics to InfluxDB: {influx_err}")

        try:
            write_churn_metric(repo_url, start_date, end_date, churn_summary)
        except Exception as influx_err:
            logger.warning(f"Failed to write churn to InfluxDB: {influx_err}")

        try:
            if daily:
                write_daily_churn_metrics(repo_url, daily)
        except Exception as influx_err:
            logger.warning(f"Failed to write daily churn to InfluxDB: {influx_err}")

        loc_response = ProjectLOCResponse(
            project_root=repo_path,
            total_loc=project_loc.total_loc,
            total_files=project_loc.total_files,
            total_blank_lines=project_loc.total_blank_lines,
            total_excluded_lines=project_loc.total_excluded_lines,
            total_comment_lines=project_loc.total_comment_lines,
            total_weighted_loc=project_loc.total_weighted_loc,
            packages=[
                PackageLOCResponse(
                    package=pkg.package,
                    loc=pkg.loc,
                    file_count=pkg.file_count,
                    comment_lines=pkg.comment_lines,
                    weighted_loc=pkg.weighted_loc,
                    files=[
                        FileLOCResponse(
                            path=f.path, total_lines=f.total_lines, loc=f.loc,
                            blank_lines=f.blank_lines, excluded_lines=f.excluded_lines,
                            comment_lines=f.comment_lines, weighted_loc=f.weighted_loc,
                        )
                        for f in pkg.files
                    ],
                )
                for pkg in project_loc.packages
            ],
            modules=[
                ModuleLOCResponse(
                    module=m.module,
                    loc=m.loc,
                    package_count=len(m.packages),
                    file_count=m.file_count,
                    comment_lines=m.comment_lines,
                    packages=[
                        PackageLOCResponse(
                            package=p.package,
                            loc=p.loc,
                            file_count=p.file_count,
                            comment_lines=p.comment_lines,
                            weighted_loc=p.weighted_loc,
                            files=[
                                FileLOCResponse(
                                    path=f.path, total_lines=f.total_lines, loc=f.loc,
                                    blank_lines=f.blank_lines, excluded_lines=f.excluded_lines,
                                    comment_lines=f.comment_lines, weighted_loc=f.weighted_loc,
                                )
                                for f in p.files
                            ],
                        )
                        for p in m.packages
                    ],
                )
                for m in project_loc.modules
            ],
            files=[
                FileLOCResponse(
                    path=f.path, total_lines=f.total_lines, loc=f.loc,
                    blank_lines=f.blank_lines, excluded_lines=f.excluded_lines,
                    comment_lines=f.comment_lines, weighted_loc=f.weighted_loc,
                )
                for f in project_loc.files
            ],
        )

        return AnalyzeResponse(
            repo_url=repo_url,
            start_date=start_date,
            end_date=end_date,
            loc=loc_response,
            churn=ChurnResponse(**churn_summary),
            churn_daily={day: ChurnResponse(**vals) for day, vals in daily.items()},
        )

    except GitCloneError as e:
        logger.error(f"Clone failed for {repo_url}: {e}")
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        logger.error(f"Analyze failed: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})
    finally:
        cloner.cleanup()


# --- WIP Metric Endpoint ---


@router.post("/metrics/wip", response_model=WIPResponse, status_code=200)
async def compute_wip(request: Request):
    """Compute WIP (Work In Progress) metric for a Taiga board."""
    try:
        body = await request.json()
    except Exception as e:
        # Normalize JSON decode errors to a clear 400 response rather than 500
        try:
            from json import JSONDecodeError
            if isinstance(e, JSONDecodeError):
                logger.warning(f"Invalid JSON body: {e}")
                return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
        except Exception:
            pass
        logger.warning(f"Failed to parse request body: {e}")
        return JSONResponse(status_code=400, content={"detail": "Invalid request body"})
    logger.info(f"WIP metric request: {body}")

    try:
        wip_request = WIPRequest(**body)
    except ValidationError as e:
        errors = e.errors()
        messages = [err["msg"] for err in errors]
        logger.warning(f"WIP validation failed: {messages}")
        return JSONResponse(
            status_code=400,
            content={"detail": messages},
        )

    kanban_url = wip_request.kanban_url
    taiga_url = wip_request.taiga_url
    recent = wip_request.recent_days

    # If kanban_url is provided, use kanban mode (task-level WIP)
    use_kanban = kanban_url is not None
    board_url = kanban_url if use_kanban else taiga_url

    try:
        if use_kanban:
            logger.info(f"Calculating kanban WIP metrics: {board_url} recent_days={recent}")
            kanban_metric = calculate_kanban_wip(board_url, recent_days=recent)

            sprint_resp = {
                "project_id": kanban_metric.project_id,
                "project_slug": kanban_metric.project_slug,
                "sprint_id": None,
                "sprint_name": "kanban",
                "date_range_start": kanban_metric.date_range_start,
                "date_range_end": kanban_metric.date_range_end,
                "daily_wip": [
                    {
                        "date": daily.date,
                        "wip_count": daily.wip_count,
                        "backlog_count": daily.backlog_count,
                        "done_count": daily.done_count,
                    }
                    for daily in kanban_metric.daily_wip
                ],
            }

            response = WIPResponse(
                project_id=kanban_metric.project_id,
                project_slug=kanban_metric.project_slug,
                sprints_count=1,
                sprints=[sprint_resp],
            )

            # Write WIP metrics to InfluxDB
            try:
                influx_result = write_wip_metrics(response.dict())
                if influx_result.success:
                    logger.info(f"WIP metrics written to InfluxDB: {influx_result.points_written} points")
                else:
                    logger.warning(f"Failed to write WIP metrics to InfluxDB: {influx_result.errors}")
            except Exception as write_error:
                logger.warning(f"Failed to write WIP metrics to InfluxDB: {write_error}")

            logger.info(f"Kanban WIP metrics calculated: {len(kanban_metric.daily_wip)} days")
            return response

        # Scrum mode: user-story WIP per sprint
        logger.info(f"Calculating daily WIP metrics for all sprints: {board_url} recent_days={recent}")
        sprints_data = calculate_daily_wip_all_sprints(board_url, recent_days=recent)

        if not sprints_data:
            logger.warning(f"No sprints found for {board_url}")
            return JSONResponse(
                status_code=404,
                content={"detail": "No sprints found for the specified project"},
            )

        # Extract project info from first sprint result
        project_id = sprints_data[0].project_id
        project_slug = sprints_data[0].project_slug

        # Build response with all sprints
        sprints_response = []
        for metric in sprints_data:
            sprint_resp = {
                "project_id": metric.project_id,
                "project_slug": metric.project_slug,
                "sprint_id": metric.sprint_id,
                "sprint_name": metric.sprint_name,
                "date_range_start": metric.date_range_start,
                "date_range_end": metric.date_range_end,
                "daily_wip": [
                    {
                        "date": daily.date,
                        "wip_count": daily.wip_count,
                        "backlog_count": daily.backlog_count,
                        "done_count": daily.done_count,
                    }
                    for daily in metric.daily_wip
                ],
            }
            sprints_response.append(sprint_resp)

        response = WIPResponse(
            project_id=project_id,
            project_slug=project_slug,
            sprints_count=len(sprints_response),
            sprints=sprints_response,
        )

        # Write WIP metrics to InfluxDB
        try:
            influx_result = write_wip_metrics(response.dict())
            if influx_result.success:
                logger.info(f"WIP metrics written to InfluxDB: {influx_result.points_written} points")
            else:
                logger.warning(f"Failed to write WIP metrics to InfluxDB: {influx_result.errors}")
        except Exception as write_error:
            logger.warning(f"Failed to write WIP metrics to InfluxDB: {write_error}")

        logger.info(f"Daily WIP metrics calculated for {len(sprints_response)} sprints")
        return response

    except ValueError as e:
        logger.warning(f"Invalid Taiga URL: {e}")
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except TaigaFetchError as e:
        logger.error(f"Taiga API error: {e}")
        return JSONResponse(status_code=503, content={"detail": str(e)})
    except Exception as e:
        logger.error(f"WIP metric calculation failed: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/snapshots/{repo_id}/latest", response_model=LatestSnapshotResponse)
async def get_latest_snapshot(repo_id: str, granularity: str = Query("project")):
    """Get the most recent metric snapshot for a repository."""
    try:
        if granularity not in ("project", "package", "file"):
            return JSONResponse(
                status_code=400,
                content={"detail": "granularity must be 'project', 'package', or 'file'"}
            )
        
        snapshot_data = query_latest_snapshot(repo_id, granularity)
        
        if not snapshot_data:
            return LatestSnapshotResponse(
                repo_id=repo_id,
                repo_name="unknown",
                latest_snapshot=None
            )
        
        snapshot_record = SnapshotRecord(
            timestamp=snapshot_data["time"].isoformat() if snapshot_data["time"] else "",
            repo_id=snapshot_data.get("repo_id", ""),
            repo_name=snapshot_data.get("repo_name", ""),
            commit_hash=snapshot_data.get("commit_hash", ""),
            branch=snapshot_data.get("branch", ""),
            granularity=snapshot_data.get("granularity", ""),
            metrics=SnapshotData(
                total_loc=0,
                code_loc=0,
                comment_loc=0,
                blank_loc=0
            ),
            file_path=snapshot_data.get("file_path"),
            package_name=snapshot_data.get("package_name")
        )
        
        return LatestSnapshotResponse(
            repo_id=repo_id,
            repo_name=snapshot_data.get("repo_name", ""),
            latest_snapshot=snapshot_record
        )
    except Exception as e:
        logger.error(f"Error querying latest snapshot: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/snapshots/{repo_id}/range", response_model=SnapshotHistoryResponse)
async def get_snapshot_history(
    repo_id: str,
    start_time: str = Query(..., description="Start timestamp (ISO 8601)"),
    end_time: str = Query(..., description="End timestamp (ISO 8601)"),
    granularity: str = Query("project", description="Granularity filter")
):
    try:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        
        if start_dt >= end_dt:
            return JSONResponse(
                status_code=400,
                content={"detail": "start_time must be before end_time"}
            )
        
        snapshots_data = query_timeseries_snapshots_by_repo(
            repo_id,
            start_dt,
            end_dt,
            granularity if granularity != "all" else None
        )
        
        snapshots = []
        repo_name = "unknown"
        
        for snap in snapshots_data:
            if not repo_name or repo_name == "unknown":
                repo_name = snap.get("repo_name", "unknown")
            
            snapshot_record = SnapshotRecord(
                timestamp=snap["time"].isoformat() if snap.get("time") else "",
                repo_id=snap.get("repo_id", ""),
                repo_name=snap.get("repo_name", ""),
                commit_hash=snap.get("commit_hash", ""),
                branch=snap.get("branch", ""),
                granularity=snap.get("granularity", ""),
                metrics=SnapshotData(
                    total_loc=0,
                    code_loc=0,
                    comment_loc=0,
                    blank_loc=0
                ),
                file_path=snap.get("file_path"),
                package_name=snap.get("package_name")
            )
            snapshots.append(snapshot_record)
        
        return SnapshotHistoryResponse(
            repo_id=repo_id,
            repo_name=repo_name,
            granularity=granularity,
            start_time=start_time,
            end_time=end_time,
            snapshots=snapshots,
            count=len(snapshots)
        )
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid timestamp format: {e}"}
        )
    except Exception as e:
        logger.error(f"Error querying snapshot history: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/snapshots/{repo_id}/at/{timestamp}", response_model=SnapshotRecord)
async def get_snapshot_at_time(repo_id: str, timestamp: str):
    try:
        target_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        
        snapshot_data = query_snapshot_at_timestamp(repo_id, target_dt)
        
        if not snapshot_data:
            return JSONResponse(
                status_code=404,
                content={"detail": f"No snapshot found for {repo_id} at or before {timestamp}"}
            )
        
        return SnapshotRecord(
            timestamp=snapshot_data["time"].isoformat() if snapshot_data.get("time") else "",
            repo_id=snapshot_data.get("repo_id", ""),
            repo_name=snapshot_data.get("repo_name", ""),
            commit_hash=snapshot_data.get("commit_hash", ""),
            branch=snapshot_data.get("branch", ""),
            granularity=snapshot_data.get("granularity", ""),
            metrics=SnapshotData(
                total_loc=0,
                code_loc=0,
                comment_loc=0,
                blank_loc=0
            ),
            file_path=snapshot_data.get("file_path"),
            package_name=snapshot_data.get("package_name")
        )
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid timestamp format: {e}"}
        )
    except Exception as e:
        logger.error(f"Error querying snapshot: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/snapshots/{repo_id}/commit/{commit_hash}", response_model=CommitSnapshotsResponse)
async def get_snapshots_for_commit(repo_id: str, commit_hash: str):
    try:
        snapshots_data = query_snapshots_by_commit(repo_id, commit_hash)
        
        snapshots = []
        repo_name = "unknown"
        
        for snap in snapshots_data:
            if not repo_name or repo_name == "unknown":
                repo_name = snap.get("repo_name", "unknown")
            
            snapshot_record = SnapshotRecord(
                timestamp=snap["time"].isoformat() if snap.get("time") else "",
                repo_id=snap.get("repo_id", ""),
                repo_name=snap.get("repo_name", ""),
                commit_hash=snap.get("commit_hash", ""),
                branch=snap.get("branch", ""),
                granularity=snap.get("granularity", ""),
                metrics=SnapshotData(
                    total_loc=0,
                    code_loc=0,
                    comment_loc=0,
                    blank_loc=0
                ),
                file_path=snap.get("file_path"),
                package_name=snap.get("package_name")
            )
            snapshots.append(snapshot_record)
        
        return CommitSnapshotsResponse(
            repo_id=repo_id,
            repo_name=repo_name,
            commit_hash=commit_hash,
            snapshots=snapshots,
            count=len(snapshots)
        )
    except Exception as e:
        logger.error(f"Error querying commit snapshots: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/commits/{repo_id}", response_model=CommitListResponse)
async def get_commits_in_range(
    repo_id: str,
    start_time: str = Query(...),
    end_time: str = Query(...),
    branch: Optional[str] = Query(None)
):
    try:
        start = _parse_timestamp(start_time)
        end = _parse_timestamp(end_time)
        
        if not start or not end:
            return JSONResponse(status_code=400, content={"detail": "Invalid timestamp format"})
        
        if start >= end:
            return JSONResponse(status_code=400, content={"detail": "start_time must be before end_time"})
        
        commits_data = query_commits_in_range(repo_id, start, end, branch)
        
        commits = [
            CommitInfo(
                commit_hash=c.get("commit_hash", ""),
                branch=c.get("branch", ""),
                time=c["time"].isoformat() if c.get("time") else ""
            )
            for c in commits_data
        ]
        
        return CommitListResponse(
            repo_id=repo_id,
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            branch=branch,
            commits=commits,
            count=len(commits)
        )
    except Exception as e:
        logger.error(f"Error querying commits: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/commits/{repo_id}/compare", response_model=CommitComparisonResponse)
async def compare_commits(
    repo_id: str,
    commit1: str = Query(...),
    commit2: str = Query(...),
    granularity: str = Query("project")
):
    try:
        if granularity not in ("project", "package", "file"):
            return JSONResponse(
                status_code=400,
                content={"detail": "granularity must be 'project', 'package', or 'file'"}
            )
        
        comparison = query_compare_commits(repo_id, commit1, commit2, granularity)
        
        return CommitComparisonResponse(
            repo_id=comparison["repo_id"],
            commit1=comparison["commit1"],
            commit2=comparison["commit2"],
            granularity=comparison["granularity"],
            snapshots_commit1=comparison["snapshots_commit1"],
            snapshots_commit2=comparison["snapshots_commit2"]
        )
    except Exception as e:
        logger.error(f"Error comparing commits: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/trend/{repo_id}", response_model=LocTrendResponse)
async def get_loc_trend(
    repo_id: str,
    start_time: str = Query(...),
    end_time: str = Query(...),
    granularity: str = Query("project")
):
    try:
        start = _parse_timestamp(start_time)
        end = _parse_timestamp(end_time)
        
        if not start or not end:
            return JSONResponse(status_code=400, content={"detail": "Invalid timestamp format"})
        
        if start >= end:
            return JSONResponse(status_code=400, content={"detail": "start_time must be before end_time"})
        
        trend_data = query_loc_trend(repo_id, start, end, granularity)
        
        trend = [
            {"time": t["time"].isoformat() if t.get("time") else "", "total_loc": t.get("total_loc", 0)}
            for t in trend_data
        ]
        
        return LocTrendResponse(
            repo_id=repo_id,
            granularity=granularity,
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            trend=trend,
            count=len(trend)
        )
    except Exception as e:
        logger.error(f"Error querying trend: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/by-branch/{repo_id}", response_model=BranchMetricsResponse)
async def get_branch_metrics(repo_id: str):
    try:
        branch_data = query_current_loc_by_branch(repo_id)
        
        branches = [
            BranchMetrics(
                branch=b.get("branch", ""),
                total_loc=b.get("total_loc", 0),
                updated_at=b["time"].isoformat() if b.get("time") else ""
            )
            for b in branch_data
        ]
        
        return BranchMetricsResponse(
            repo_id=repo_id,
            branches=branches,
            count=len(branches)
        )
    except Exception as e:
        logger.error(f"Error querying branch metrics: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/metrics/timeseries/change/{repo_id}", response_model=LocChangeResponse)
async def get_loc_change(
    repo_id: str,
    timestamp1: str = Query(...),
    timestamp2: str = Query(...),
    granularity: str = Query("project")
):
    try:
        ts1 = _parse_timestamp(timestamp1)
        ts2 = _parse_timestamp(timestamp2)
        
        if not ts1 or not ts2:
            return JSONResponse(status_code=400, content={"detail": "Invalid timestamp format"})
        
        if granularity not in ("project", "package", "file"):
            return JSONResponse(
                status_code=400,
                content={"detail": "granularity must be 'project', 'package', or 'file'"}
            )
        
        change = query_loc_change_between(repo_id, ts1, ts2, granularity)
        
        return LocChangeResponse(**change)
    except Exception as e:
        logger.error(f"Error calculating change: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


# ============================================================================
# Code Quality Metrics Endpoints
# ============================================================================

from src.services.fog_index import analyze_root as analyze_fog_index_root
from src.services.class_coverage import analyze_repo as analyze_class_coverage_repo
from src.services.method_coverage import scan_repo as scan_method_coverage_repo
from src.services.taiga_metrics import (
    CYCLE_TIME_END_STATES,
    CYCLE_TIME_START_STATES,
    get_adopted_work as get_taiga_adopted_work_data,
    get_transition_history as get_taiga_transition_history_data,
    parse_utc as parse_taiga_utc,
)
from src.services.taiga_metrics import get_adopted_work as get_taiga_adopted_work_data
from src.services.taiga_metrics import get_transition_history as get_taiga_transition_history_data
from src.services.cycle_time import compute_cycle_times, summarize_cycle_times
import shutil


@router.post("/metrics/fog-index", response_model=FogIndexMetricResponse, status_code=200)
async def compute_fog_index(request: Request):
    """Compute Fog Index (readability of comments) for a GitHub repository."""
    body = await request.json()
    logger.info(f"Fog Index metric request: {body}")
    
    try:
        user = body.get("user")
        repo = body.get("repo")
        branch = body.get("branch", "main")
        
        if not user or not repo:
            return JSONResponse(
                status_code=400,
                content={"detail": "Missing 'user' or 'repo' parameter"}
            )
        
        # Download and analyze repository
        cloner = GitRepoCloner()
        repo_path = cloner.clone(f"https://github.com/{user}/{repo}", shallow=True)
        
        try:
            fog_results = analyze_fog_index_root(
                Path(repo_path),
                high_threshold=body.get("high_threshold", 12.0),
                low_threshold=body.get("low_threshold", 5.0),
                min_comment_words=body.get("min_comment_words", 10),
                min_words=body.get("min_words", 30),
            )
            
            files_result = [
                {
                    "score": r[0],
                    "status": r[1],
                    "kind": r[2],
                    "path": str(r[3]),
                    "message": r[4]
                }
                for r in fog_results
            ]
            
            # Write to InfluxDB
            try:
                write_fog_index_metrics(
                    repo_name=repo,
                    branch=branch,
                    files_results=fog_results,
                    commit_sha=cloner.commit_hash or "",
                )
            except Exception as influx_err:
                logger.warning(f"Failed to write fog index metrics to InfluxDB: {influx_err}")
            
            return FogIndexMetricResponse(
                repository=f"{user}/{repo}",
                branch=branch,
                commit_sha=cloner.commit_hash or "",
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                files=files_result,
                summary={"file_count": len(files_result)}
            )
        finally:
            cloner.cleanup()
    
    except Exception as e:
        logger.error(f"Fog Index analysis failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )


@router.post("/metrics/class-coverage", response_model=ClassCoverageMetricResponse, status_code=200)
async def compute_class_coverage(request: Request):
    """Compute class comment coverage (JavaDoc for classes) for a GitHub repository."""
    body = await request.json()
    logger.info(f"Class Coverage metric request: {body}")
    
    try:
        user = body.get("user")
        repo = body.get("repo")
        branch = body.get("branch", "main")
        
        if not user or not repo:
            return JSONResponse(
                status_code=400,
                content={"detail": "Missing 'user' or 'repo' parameter"}
            )
        
        # Download and analyze repository
        cloner = GitRepoCloner()
        repo_path = cloner.clone(f"https://github.com/{user}/{repo}", shallow=True)
        
        try:
            coverage_data = analyze_class_coverage_repo(
                str(repo_path),
                user,
                repo,
                f"https://github.com/{user}/{repo}",
                branch,
                cloner.commit_hash or ""
            )
            
            # Extract summary
            summary = coverage_data.get("summary", {})
            files_analyzed = coverage_data.get("files_analyzed", [])
            
            # Write to InfluxDB
            try:
                write_class_coverage_metrics(
                    repo_name=repo,
                    branch=branch,
                    total_classes=summary.get("total_classes_found", 0),
                    documented_classes=summary.get("classes_with_javadoc", 0),
                    coverage_percent=summary.get("coverage_pct", 0.0),
                    commit_sha=cloner.commit_hash or "",
                    files_detail=[
                        {
                            "file_path": f.get("file_path", ""),
                            "total_classes": f.get("total_classes", 0),
                            "documented_classes": f.get("documented_classes", 0),
                            "coverage_percent": f.get("coverage_percent", 0.0),
                        }
                        for f in files_analyzed
                    ] if files_analyzed else None
                )
            except Exception as influx_err:
                logger.warning(f"Failed to write class coverage metrics to InfluxDB: {influx_err}")
            
            return ClassCoverageMetricResponse(
                repository=f"{user}/{repo}",
                branch=branch,
                commit_sha=cloner.commit_hash or "",
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_java_files=summary.get("total_java_files_analyzed", 0),
                total_classes=summary.get("total_classes_found", 0),
                documented_classes=summary.get("classes_with_javadoc", 0),
                overall_coverage_percent=summary.get("coverage_pct", 0.0),
                files=[
                    {
                        "file_path": f.get("file_path", ""),
                        "total_classes": f.get("total_classes", 0),
                        "documented_classes": f.get("documented_classes", 0),
                        "coverage_percent": f.get("coverage_percent", 0.0),
                    }
                    for f in files_analyzed
                ]
            )
        finally:
            cloner.cleanup()
    
    except Exception as e:
        logger.error(f"Class Coverage analysis failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )


@router.post("/metrics/method-coverage", response_model=MethodCoverageMetricResponse, status_code=200)
async def compute_method_coverage(request: Request):
    """Compute method comment coverage (JavaDoc for methods by visibility) for a GitHub repository."""
    body = await request.json()
    logger.info(f"Method Coverage metric request: {body}")
    
    try:
        user = body.get("user")
        repo = body.get("repo")
        branch = body.get("branch", "main")
        
        if not user or not repo:
            return JSONResponse(
                status_code=400,
                content={"detail": "Missing 'user' or 'repo' parameter"}
            )
        
        # Download and analyze repository
        cloner = GitRepoCloner()
        repo_path = cloner.clone(f"https://github.com/{user}/{repo}", shallow=True)
        
        try:
            coverage_data = scan_method_coverage_repo(Path(repo_path))
            
            public_cov = coverage_data.get("public", {}).get("coverage", 0.0)
            protected_cov = coverage_data.get("protected", {}).get("coverage", 0.0)
            # Service groups package-private methods under "default".
            package_cov = coverage_data.get("default", {}).get("coverage", 0.0)
            private_cov = coverage_data.get("private", {}).get("coverage", 0.0)
            
            # Write to InfluxDB
            try:
                write_method_coverage_metrics(
                    repo_name=repo,
                    branch=branch,
                    public_coverage=public_cov,
                    protected_coverage=protected_cov,
                    package_coverage=package_cov,
                    private_coverage=private_cov,
                    commit_sha=cloner.commit_hash or "",
                )
            except Exception as influx_err:
                logger.warning(f"Failed to write method coverage metrics to InfluxDB: {influx_err}")
            
            return MethodCoverageMetricResponse(
                repository=f"{user}/{repo}",
                branch=branch,
                commit_sha=cloner.commit_hash or "",
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                public_coverage_percent=public_cov,
                protected_coverage_percent=protected_cov,
                package_coverage_percent=package_cov,
                private_coverage_percent=private_cov,
                summary=coverage_data
            )
        finally:
            cloner.cleanup()
    
    except Exception as e:
        logger.error(f"Method Coverage analysis failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )


@router.post("/metrics/taiga-metrics", response_model=TaigaMetricsResponse, status_code=200)
async def compute_taiga_metrics(request: Request):
    """Compute Taiga project metrics (adopted work per sprint)."""
    body = await request.json()
    logger.info(f"Taiga Metrics request: {body}")
    
    try:
        base_url = body.get("base_url", "")
        slug = body.get("slug", "")
        taiga_id = body.get("taiga_id", -1)
        
        if not slug and taiga_id < 0:
            return JSONResponse(
                status_code=400,
                content={"detail": "Missing 'slug' or 'taiga_id' parameter"}
            )
        
        # Get Taiga data
        taiga_data = get_taiga_adopted_work_data(base_url, slug, taiga_id)
        
        if isinstance(taiga_data, dict) and taiga_data.get("status") == "error":
            return JSONResponse(
                status_code=400,
                content=taiga_data
            )
        
        sprints_result = []
        if "sprints" in taiga_data:
            for sprint in taiga_data["sprints"]:
                sprints_result.append({
                    "sprint_id": sprint.get("sprint_id", 0),
                    "sprint_name": sprint.get("sprint_name", ""),
                    "adopted_work_count": sprint.get("adopted_count", 0),
                    "created_stories": sprint.get("created_stories", 0),
                    "completed_stories": sprint.get("completed_stories", 0),
                })

        cycle_time_data = []
        transition_data = get_taiga_transition_history_data(base_url, slug, taiga_id)
        if isinstance(transition_data, dict) and transition_data.get("status") == "success":
            for story in transition_data.get("stories", []):
                start_ts = None
                end_ts = None

                for transition in story.get("transitions", []):
                    to_status = transition.get("to_status")
                    timestamp = transition.get("timestamp")
                    if not timestamp:
                        continue

                    if start_ts is None and to_status in CYCLE_TIME_START_STATES:
                        start_ts = timestamp
                        continue

                    if start_ts is not None and to_status in CYCLE_TIME_END_STATES:
                        end_ts = timestamp
                        break

                if not start_ts or not end_ts:
                    continue

                start_dt = parse_taiga_utc(start_ts)
                end_dt = parse_taiga_utc(end_ts)
                if start_dt is None or end_dt is None or end_dt < start_dt:
                    continue

                cycle_time_data.append(
                    {
                        "user_story_id": story.get("user_story_id"),
                        "user_story_name": story.get("user_story_name", ""),
                        "start_timestamp": start_ts,
                        "end_timestamp": end_ts,
                        "cycle_time_hours": (end_dt - start_dt).total_seconds() / 3600.0,
                    }
                )
        elif isinstance(transition_data, dict):
            logger.warning(f"Could not fetch transition history for cycle time persistence: {transition_data}")
        
        # Write to InfluxDB
        try:
            write_taiga_metrics(
                project_slug=slug or f"taiga_{taiga_id}",
                sprints_data=sprints_result,
                cycle_time_data=cycle_time_data,
            )
        except Exception as influx_err:
            logger.warning(f"Failed to write taiga metrics to InfluxDB: {influx_err}")

        avg_cycle_time_hours = (
            sum(item["cycle_time_hours"] for item in cycle_time_data) / len(cycle_time_data)
            if cycle_time_data else None
        )
        
        return TaigaMetricsResponse(
            project_id=taiga_data.get("project_id", taiga_id),
            project_slug=taiga_data.get("project_slug", slug),
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            sprints=sprints_result,
            summary={
                "sprint_count": len(sprints_result),
                "cycle_time_story_count": len(cycle_time_data),
                "average_cycle_time_hours": avg_cycle_time_hours,
            }
        )
    
    except Exception as e:
        logger.error(f"Taiga metrics computation failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )


@router.get("/cycle-time", response_model=CycleTimeResponse, status_code=200)
async def get_cycle_time_metrics(
    start: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end: str = Query(..., description="End date in YYYY-MM-DD format"),
    slug: str = Query("", description="Taiga project slug"),
    taiga_id: int = Query(-1, description="Taiga project ID (alternative to slug)"),
    base_url: str = Query("", description="Taiga API base URL"),
    sprint_id: Optional[int] = Query(None, description="Optional Taiga sprint/milestone ID"),
):
    """Compute cycle-time metrics for Taiga user stories in a date range."""
    try:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid date format. Use YYYY-MM-DD for 'start' and 'end'."},
            )

        if start_date > end_date:
            return JSONResponse(
                status_code=400,
                content={"detail": "'start' must be less than or equal to 'end'."},
            )

        if not slug and taiga_id < 0:
            return JSONResponse(
                status_code=400,
                content={"detail": "Missing 'slug' or 'taiga_id' parameter"},
            )

        transition_history = get_taiga_transition_history_data(base_url, slug, taiga_id, sprint_id)

        if isinstance(transition_history, dict) and transition_history.get("status") == "error":
            return JSONResponse(status_code=400, content=transition_history)

        stories_for_cycle_time = []
        for story in transition_history.get("stories", []):
            filtered_transitions = []

            for transition in story.get("transitions", []):
                to_status = transition.get("to_status")
                timestamp = transition.get("timestamp")
                if not to_status or not timestamp:
                    continue

                try:
                    transition_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    continue

                if start_date <= transition_dt.date() <= end_date:
                    filtered_transitions.append(
                        {
                            "status": to_status,
                            "timestamp": transition_dt.isoformat(),
                        }
                    )

            stories_for_cycle_time.append(
                {
                    "story_id": story.get("user_story_id"),
                    "transitions": filtered_transitions,
                }
            )

        cycle_time_results = compute_cycle_times(stories_for_cycle_time)
        summary = summarize_cycle_times(cycle_time_results)
       
        # writing cycle time metrics to InfluxDB
        try:
            write_cycle_time_metrics(
                project_slug=slug or f"taiga_{taiga_id}",
                story_cycle_times=cycle_time_results,
                sprint_id=sprint_id,
                end_date=end,
            )
        except Exception as influx_err:
            logger.warning(f"Failed to write cycle time metrics to InfluxDB: {influx_err}")

        return CycleTimeResponse(
            project_id=transition_history.get("project_id", taiga_id),
            project_slug=transition_history.get("project_slug", slug),
            sprint_id=transition_history.get("sprint_id"),
            start_date=start,
            end_date=end,
            story_cycle_times=cycle_time_results,
            summary=summary,
        )

    except Exception as e:
        logger.error(f"Cycle time metrics computation failed: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

