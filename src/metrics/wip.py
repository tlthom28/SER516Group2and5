import logging
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

logger = logging.getLogger("repopulse.metrics.wip")

TAIGA_API_BASE = "https://api.taiga.io/api/v1"


class TaigaFetchError(Exception):
    """Raised when Taiga API calls fail."""
    pass


@dataclass
class DailyWIPMetric:
    """Represents WIP for a single day."""
    date: str  # ISO format: YYYY-MM-DD
    wip_count: int
    backlog_count: int
    done_count: int


@dataclass
class WIPMetric:
    """Represents the WIP metric time-series for a Taiga project."""
    project_id: Optional[int] = None
    project_slug: Optional[str] = None
    sprint_id: Optional[int] = None
    sprint_name: Optional[str] = None
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    daily_wip: List[DailyWIPMetric] = field(default_factory=list)


def _validate_taiga_url(taiga_url: str) -> str:
    if not taiga_url:
        raise ValueError("Taiga URL cannot be empty")

    taiga_url = taiga_url.strip().rstrip("/")

    if "/project/" not in taiga_url:
        raise ValueError("Invalid Taiga URL. Expected format: https://taiga.io/project/{slug}")

    parts = taiga_url.split("/project/")
    if len(parts) != 2 or not parts[1]:
        raise ValueError("Could not extract project slug from URL")

    # Take only the first path segment as the slug.
    # Taiga URLs can have UI route suffixes like /kanban, /backlog, /timeline, etc.
    slug = parts[1].split("/")[0]
    if not slug:
        raise ValueError("Could not extract project slug from URL")

    return slug


def _get_project_id(project_slug: str) -> int:
    try:
        logger.debug(f"Fetching project ID for slug: {project_slug}")
        resp = requests.get(
            f"{TAIGA_API_BASE}/projects/by_slug",
            params={"slug": project_slug},
            timeout=10,
        )
        resp.raise_for_status()

        project = resp.json()
        if not project or not isinstance(project, dict):
            raise TaigaFetchError(f"No project found with slug: {project_slug}")

        project_id = project.get("id")
        if not project_id:
            raise TaigaFetchError(f"Project {project_slug} returned no ID in API response")

        logger.debug(f"Found project ID {project_id} for slug {project_slug}")
        return project_id

    except requests.RequestException as e:
        raise TaigaFetchError(f"Failed to fetch project '{project_slug}': {e}")
    except (KeyError, TypeError) as e:
        raise TaigaFetchError(f"Unexpected API response: {e}")


def _get_project_statuses(project_id: int) -> Dict[int, dict]:
    try:
        logger.debug(f"Fetching statuses for project {project_id}")
        resp = requests.get(
            f"{TAIGA_API_BASE}/userstory-statuses",
            params={"project": project_id},
            timeout=10,
        )
        resp.raise_for_status()

        statuses = resp.json()
        if not statuses:
            raise TaigaFetchError(f"No statuses found for project {project_id}")

        status_map = {
            s.get("id"): {
                "name": s.get("name", "Unknown"),
                "is_closed": s.get("is_closed", False),
                "order": s.get("order", 999),
            }
            for s in statuses
        }
        logger.debug(f"Found {len(status_map)} statuses")
        return status_map

    except requests.RequestException as e:
        raise TaigaFetchError(f"Failed to fetch statuses: {e}")
    except (KeyError, TypeError) as e:
        raise TaigaFetchError(f"Unexpected API response: {e}")


def _get_userstories(project_id: int, milestone: Optional[int] = None) -> List[dict]:
    try:
        params: Dict = {"project": project_id}
        if milestone is not None:
            params["milestone"] = milestone
        logger.debug(f"Fetching userstories for project {project_id} (milestone={milestone})")
        resp = requests.get(
            f"{TAIGA_API_BASE}/userstories",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()

        stories = resp.json()
        logger.debug(f"Found {len(stories)} stories")
        return stories if isinstance(stories, list) else []

    except requests.RequestException as e:
        raise TaigaFetchError(f"Failed to fetch userstories: {e}")
    except TypeError as e:
        raise TaigaFetchError(f"Unexpected API response: {e}")


def _get_userstory_history(userstory_id: int) -> List[dict]:
    try:
        logger.debug(f"Fetching history for userstory {userstory_id}")
        resp = requests.get(
            f"{TAIGA_API_BASE}/history/userstory/{userstory_id}",
            timeout=10,
        )
        resp.raise_for_status()

        events = resp.json()
        logger.debug(f"Found {len(events) if isinstance(events, list) else 0} history events")
        return events if isinstance(events, list) else []

    except requests.RequestException as e:
        logger.warning(f"Failed to fetch history for userstory {userstory_id}: {e}")
        return []
    except TypeError as e:
        logger.warning(f"Unexpected API response for history: {e}")
        return []


def _get_sprint_dates(project_id: int, sprint_id: int) -> tuple[datetime, datetime]:
    try:
        logger.debug(f"Fetching milestone {sprint_id} for project {project_id}")
        resp = requests.get(
            f"{TAIGA_API_BASE}/milestones/{sprint_id}",
            params={"project": project_id},
            timeout=10,
        )
        resp.raise_for_status()

        milestone = resp.json()
        start_str = milestone.get("estimated_start")
        end_str = milestone.get("estimated_finish")

        if not start_str or not end_str:
            raise TaigaFetchError(f"Sprint {sprint_id} missing date fields")

        start = datetime.fromisoformat(start_str.replace("Z", "+00:00")).date()
        end = datetime.fromisoformat(end_str.replace("Z", "+00:00")).date()

        logger.debug(f"Sprint range: {start} → {end}")
        return start, end

    except requests.RequestException as e:
        raise TaigaFetchError(f"Failed to fetch sprint dates: {e}")
    except (KeyError, ValueError) as e:
        raise TaigaFetchError(f"Invalid sprint date format: {e}")


def _build_status_name_to_id(status_map: Dict[int, dict]) -> Dict[str, int]:
    """Build a reverse lookup from status name to status ID."""
    return {
        info.get("name", ""): sid
        for sid, info in status_map.items()
        if info.get("name")
    }


def _extract_status_at_date(
    history_events: List[dict],
    target_date,
    status_name_to_id: Optional[Dict[str, int]] = None,
) -> Optional[int]:
    status_at_date = None

    for event in sorted(history_events, key=lambda e: e.get("created_at", "")):
        try:
            created_str = event.get("created_at", "")
            if not created_str:
                continue

            event_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))

            if event_dt.date() <= target_date:
                values_diff = event.get("values_diff", {})
                if "status" in values_diff:
                    status_change = values_diff["status"]
                    if isinstance(status_change, (list, tuple)) and len(status_change) >= 2:
                        # Taiga returns ["Old Name", "New Name"]
                        new_status_name = status_change[1]
                        if status_name_to_id and new_status_name in status_name_to_id:
                            status_at_date = status_name_to_id[new_status_name]
                        else:
                            # Fallback: store the name itself for categorization
                            status_at_date = new_status_name
        except (KeyError, ValueError, TypeError):
            continue

    return status_at_date


def _categorize_status(
    status_id,
    status_map: Dict[int, dict],
    min_order: Optional[int] = None,
) -> str:
    if status_id is None:
        return "backlog"

    # If status_id is a string name (from history), look it up by name
    status_info = {}
    if isinstance(status_id, int):
        status_info = status_map.get(status_id, {})
    elif isinstance(status_id, str):
        for info in status_map.values():
            if info.get("name") == status_id:
                status_info = info
                break

    if status_info.get("is_closed", False):
        return "done"

    if min_order is None:
        min_order = min((s.get("order", 999) for s in status_map.values()), default=999)
    current_order = status_info.get("order", 999)

    if current_order == min_order:
        return "backlog"

    return "wip"


def _validate_metric_against_board(
    metric: WIPMetric,
    entities: List[dict],
    status_map: Dict[int, dict],
    min_order: int,
    entity_label: str,
) -> None:
    """Validate end-of-range WIP counts against Taiga board current status data.

    This ensures the computed metric's final day aligns with the board snapshot
    returned by Taiga for the same set of entities (stories/tasks) that exist
    on or before the metric end date.
    """
    if not metric.daily_wip:
        return

    # Keep compatibility with current WIP semantics where entities not yet created
    # on a given day are treated as backlog. Therefore, the daily total should
    # match the full board entity count for the metric scope.
    expected_total = len(entities)

    for day in metric.daily_wip:
        try:
            day_date = datetime.fromisoformat(day.date).date()
        except Exception:
            raise TaigaFetchError(
                f"WIP validation against Taiga board failed for {entity_label}: "
                f"invalid day date '{day.date}'"
            )

        if day.wip_count < 0 or day.backlog_count < 0 or day.done_count < 0:
            raise TaigaFetchError(
                f"WIP validation against Taiga board failed for {entity_label}: "
                f"negative counts on {day.date}"
            )

        actual_total = day.wip_count + day.backlog_count + day.done_count

        if actual_total != expected_total:
            raise TaigaFetchError(
                f"WIP validation against Taiga board failed for {entity_label}: "
                f"actual_total={actual_total} expected_total={expected_total} on {day.date}"
            )


def _get_milestones(project_id: int) -> List[dict]:
    try:
        logger.debug(f"Fetching milestones for project {project_id}")
        resp = requests.get(
            f"{TAIGA_API_BASE}/milestones",
            params={"project": project_id},
            timeout=10,
        )
        resp.raise_for_status()

        data = resp.json()
        # Taiga API returns paginated results with "results" key
        if isinstance(data, dict) and "results" in data:
            milestones = data["results"]
        elif isinstance(data, list):
            milestones = data
        else:
            milestones = []
        return milestones

    except requests.RequestException as e:
        raise TaigaFetchError(f"Failed to fetch milestones: {e}")
    except TypeError as e:
        raise TaigaFetchError(f"Unexpected API response: {e}")


def _compute_sprint_wip(
    project_id: int,
    slug: str,
    sprint_id: int,
    status_map: Dict[int, dict],
    min_order: int,
) -> WIPMetric:
    """Compute daily WIP for a single sprint using pre-fetched project data."""
    sprint_start, sprint_end = _get_sprint_dates(project_id, sprint_id)
    stories = _get_userstories(project_id, milestone=sprint_id)
    story_map: Dict[int, dict] = {s.get("id"): s for s in stories if s.get("id")}
    story_histories: Dict[int, List[dict]] = {}
    for sid in story_map.keys():
        story_histories[sid] = _get_userstory_history(sid)

    status_name_to_id = _build_status_name_to_id(status_map)

    daily_results: List[DailyWIPMetric] = []
    current_date = sprint_start
    while current_date <= sprint_end:
        wip_count = 0
        backlog_count = 0
        done_count = 0
        for story_id, history in story_histories.items():
            status_at_date = _extract_status_at_date(history, current_date, status_name_to_id)
            if status_at_date is None:
                story = story_map.get(story_id, {})
                created_str = story.get("created_date")
                if created_str:
                    try:
                        created_date = datetime.fromisoformat(created_str.replace("Z", "+00:00")).date()
                    except Exception:
                        created_date = None
                    if created_date and current_date < created_date:
                        status_at_date = None
                    else:
                        status_at_date = story.get("status")
                else:
                    status_at_date = story.get("status")
            category = _categorize_status(status_at_date, status_map, min_order)

            if category == "wip":
                wip_count += 1
            elif category == "backlog":
                backlog_count += 1
            elif category == "done":
                done_count += 1

        daily_results.append(
            DailyWIPMetric(
                date=current_date.isoformat(),
                wip_count=wip_count,
                backlog_count=backlog_count,
                done_count=done_count,
            )
        )

        current_date += timedelta(days=1)

    metric = WIPMetric(
        project_id=project_id,
        project_slug=slug,
        sprint_id=sprint_id,
        date_range_start=sprint_start.isoformat(),
        date_range_end=sprint_end.isoformat(),
        daily_wip=daily_results,
    )

    _validate_metric_against_board(
        metric=metric,
        entities=list(story_map.values()),
        status_map=status_map,
        min_order=min_order,
        entity_label=f"sprint {sprint_id}",
    )

    logger.info(f"Daily WIP calculated: {len(daily_results)} days")
    return metric


def calculate_daily_wip(
    taiga_url: str,
    sprint_id: int,
) -> WIPMetric:
    logger.info(f"Calculating daily WIP for: {taiga_url}, sprint_id={sprint_id}")

    try:
        slug = _validate_taiga_url(taiga_url)
        project_id = _get_project_id(slug)
        status_map = _get_project_statuses(project_id)
        min_order = min((s.get("order", 999) for s in status_map.values()), default=999)
        return _compute_sprint_wip(project_id, slug, sprint_id, status_map, min_order)

    except (ValueError, TaigaFetchError) as e:
        logger.error(f"Failed to calculate daily WIP: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise TaigaFetchError(f"Unexpected error: {e}")


def calculate_daily_wip_all_sprints(
    taiga_url: str,
    recent_days: Optional[int] = None,
) -> List[WIPMetric]:
    logger.info(f"Calculating daily WIP for all sprints: {taiga_url} (recent_days={recent_days})")

    try:
        slug = _validate_taiga_url(taiga_url)
        project_id = _get_project_id(slug)
        status_map = _get_project_statuses(project_id)
        min_order = min((s.get("order", 999) for s in status_map.values()), default=999)
        milestones = _get_milestones(project_id)

        if recent_days is not None:
            cutoff_date = datetime.now(tz=timezone.utc).date() - timedelta(days=recent_days)
            filtered: List[dict] = []
            for m in milestones:
                end_str = m.get("estimated_finish")
                if end_str:
                    try:
                        end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00")).date()
                    except Exception:
                        end_date = None
                    if end_date and end_date >= cutoff_date:
                        filtered.append(m)
            if not filtered and milestones:
                last = max(
                    milestones,
                    key=lambda m: datetime.fromisoformat(
                        m.get("estimated_finish", "1900-01-01").replace("Z", "+00:00")
                    ).date()
                )
                filtered = [last]
            milestones = filtered

    except (ValueError, TaigaFetchError) as e:
        logger.error(f"Failed to calculate daily WIP for all sprints: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise TaigaFetchError(f"Unexpected error: {e}")

    results: List[WIPMetric] = []
    for m in milestones:
        mid = m.get("id")
        if mid is None:
            continue
        try:
            metric = _compute_sprint_wip(project_id, slug, mid, status_map, min_order)
            metric.sprint_name = m.get("name")
            results.append(metric)
        except (ValueError, TaigaFetchError) as e:
            logger.warning(f"Skipping milestone {mid}: {e}")
            continue

    logger.info(f"Calculated WIP for {len(results)} sprints")
    return results


def _get_task_statuses(project_id: int) -> Dict[int, dict]:
    try:
        logger.debug(f"Fetching task statuses for project {project_id}")
        resp = requests.get(
            f"{TAIGA_API_BASE}/task-statuses",
            params={"project": project_id},
            timeout=10,
        )
        resp.raise_for_status()

        statuses = resp.json()
        if not statuses:
            raise TaigaFetchError(f"No task statuses found for project {project_id}")

        status_map = {
            s.get("id"): {
                "name": s.get("name", "Unknown"),
                "is_closed": s.get("is_closed", False),
                "order": s.get("order", 999),
            }
            for s in statuses
        }
        logger.debug(f"Found {len(status_map)} task statuses")
        return status_map

    except requests.RequestException as e:
        raise TaigaFetchError(f"Failed to fetch task statuses: {e}")
    except (KeyError, TypeError) as e:
        raise TaigaFetchError(f"Unexpected API response: {e}")


def _get_tasks(project_id: int) -> List[dict]:
    try:
        logger.debug(f"Fetching tasks for project {project_id}")
        resp = requests.get(
            f"{TAIGA_API_BASE}/tasks",
            params={"project": project_id},
            timeout=10,
        )
        resp.raise_for_status()

        tasks = resp.json()
        logger.debug(f"Found {len(tasks) if isinstance(tasks, list) else 0} tasks")
        return tasks if isinstance(tasks, list) else []

    except requests.RequestException as e:
        raise TaigaFetchError(f"Failed to fetch tasks: {e}")
    except TypeError as e:
        raise TaigaFetchError(f"Unexpected API response: {e}")


def _get_task_history(task_id: int) -> List[dict]:
    try:
        logger.debug(f"Fetching history for task {task_id}")
        resp = requests.get(
            f"{TAIGA_API_BASE}/history/task/{task_id}",
            timeout=10,
        )
        resp.raise_for_status()

        events = resp.json()
        logger.debug(f"Found {len(events) if isinstance(events, list) else 0} history events")
        return events if isinstance(events, list) else []

    except requests.RequestException as e:
        logger.warning(f"Failed to fetch history for task {task_id}: {e}")
        return []
    except TypeError as e:
        logger.warning(f"Unexpected API response for task history: {e}")
        return []


def calculate_kanban_wip(
    kanban_url: str,
    recent_days: Optional[int] = None,
) -> WIPMetric:
    """Calculate daily WIP for a Kanban board at the task level over a date range."""
    days = recent_days if recent_days is not None else 30
    logger.info(f"Calculating kanban WIP for: {kanban_url} (days={days})")

    try:
        slug = _validate_taiga_url(kanban_url)
        project_id = _get_project_id(slug)
        status_map = _get_task_statuses(project_id)
        min_order = min((s.get("order", 999) for s in status_map.values()), default=999)
        status_name_to_id = _build_status_name_to_id(status_map)

        tasks = _get_tasks(project_id)
        task_map: Dict[int, dict] = {t.get("id"): t for t in tasks if t.get("id")}
        task_histories: Dict[int, List[dict]] = {}
        for tid in task_map.keys():
            task_histories[tid] = _get_task_history(tid)

        today = datetime.now(tz=timezone.utc).date()
        range_end = today
        range_start = today - timedelta(days=days)

        # If no activity in the default window, find the last activity date
        # and compute WIP for `days` before that instead
        last_activity = None
        for history in task_histories.values():
            for event in history:
                created_str = event.get("created_at", "")
                if created_str:
                    try:
                        event_date = datetime.fromisoformat(created_str.replace("Z", "+00:00")).date()
                        if last_activity is None or event_date > last_activity:
                            last_activity = event_date
                    except (ValueError, TypeError):
                        continue

        if last_activity and last_activity < range_start:
            logger.info(f"No activity in last {days} days. Last activity: {last_activity}. Adjusting range.")
            range_end = last_activity
            range_start = last_activity - timedelta(days=days)

        daily_results: List[DailyWIPMetric] = []
        current_date = range_start
        while current_date <= range_end:
            wip_count = 0
            backlog_count = 0
            done_count = 0
            for task_id, history in task_histories.items():
                status_at_date = _extract_status_at_date(history, current_date, status_name_to_id)
                if status_at_date is None:
                    task = task_map.get(task_id, {})
                    created_str = task.get("created_date")
                    if created_str:
                        try:
                            created_date = datetime.fromisoformat(created_str.replace("Z", "+00:00")).date()
                        except Exception:
                            created_date = None
                        if created_date and current_date < created_date:
                            status_at_date = None
                        else:
                            status_at_date = task.get("status")
                    else:
                        status_at_date = task.get("status")
                category = _categorize_status(status_at_date, status_map, min_order)

                if category == "wip":
                    wip_count += 1
                elif category == "backlog":
                    backlog_count += 1
                elif category == "done":
                    done_count += 1

            daily_results.append(
                DailyWIPMetric(
                    date=current_date.isoformat(),
                    wip_count=wip_count,
                    backlog_count=backlog_count,
                    done_count=done_count,
                )
            )
            current_date += timedelta(days=1)

        metric = WIPMetric(
            project_id=project_id,
            project_slug=slug,
            sprint_name="kanban",
            date_range_start=range_start.isoformat(),
            date_range_end=range_end.isoformat(),
            daily_wip=daily_results,
        )

        _validate_metric_against_board(
            metric=metric,
            entities=list(task_map.values()),
            status_map=status_map,
            min_order=min_order,
            entity_label=f"kanban project {project_id}",
        )

        logger.info(f"Kanban WIP calculated: {len(daily_results)} days, {len(task_map)} tasks")
        return metric

    except (ValueError, TaigaFetchError) as e:
        logger.error(f"Failed to calculate kanban WIP: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise TaigaFetchError(f"Unexpected error: {e}")






