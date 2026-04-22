import logging
import os
import subprocess
from datetime import date, datetime, timezone

logger = logging.getLogger("repopulse.metrics.git_history")


def get_commit_history(
    repo_path: str,
    start_date: str,
    end_date: str,
) -> list[dict]:

    if not os.path.isdir(repo_path):
        raise ValueError(f"Repository path does not exist: {repo_path}")

    git_dir = os.path.join(repo_path, ".git")
    if not os.path.isdir(git_dir):
        raise ValueError(f"Not a git repository (missing .git): {repo_path}")

    try:
        start = date.fromisoformat(start_date)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid start_date '{start_date}': {exc}") from exc

    try:
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid end_date '{end_date}': {exc}") from exc

    if start > end:
        raise ValueError(
            f"start_date ({start_date}) must be <= end_date ({end_date})"
        )

    since_ts = f"{start_date} 00:00:00 +0000"
    until_ts = f"{end_date} 23:59:59 +0000"

    cmd = [
        "git",
        "--no-pager",
        "-C",
        repo_path,
        "log",
        f"--since={since_ts}",
        f"--until={until_ts}",
        "--pretty=format:%H|%cI",
    ]

    logger.info(f"git log command: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise ValueError(f"git log failed: {result.stderr.strip()}")

    raw = result.stdout.strip()
    logger.info(f"git log returned {len(raw.splitlines()) if raw else 0} lines of output")
    if not raw:
        logger.info("No commits found in date range")
        return []

    commits: list[dict] = []

    for line in raw.splitlines():
        parts = line.split("|", maxsplit=1)
        if len(parts) != 2:
            continue

        sha, iso_str = parts[0].strip(), parts[1].strip()

        try:
            dt = datetime.fromisoformat(iso_str)
            commit_date = dt.astimezone(timezone.utc).date()
            date_str = commit_date.isoformat()
        except ValueError:
            continue

        if start <= commit_date <= end:
            commits.append({"hash": sha, "date": date_str})

    logger.info(
        "Filtered %d commits in range %s..%s; sample=%s",
        len(commits),
        start_date,
        end_date,
        commits[:10],
    )
    return commits
