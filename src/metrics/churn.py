import logging
import os
import subprocess

from src.metrics.git_history import get_commit_history

logger = logging.getLogger("repopulse.metrics.churn")


def compute_repo_churn(repo_path: str, start_date: str, end_date: str) -> dict:
    commits = get_commit_history(repo_path, start_date, end_date)
    logger.info(f"Churn: found {len(commits)} commits between {start_date} and {end_date}")

    total_added = 0
    total_deleted = 0

    for commit in commits:
        churn = compute_commit_churn(repo_path, commit["hash"])
        logger.debug(f"Commit {commit['hash'][:8]}: +{churn['added']} -{churn['deleted']}")
        total_added += churn["added"]
        total_deleted += churn["deleted"]

    result = {
        "added": total_added,
        "deleted": total_deleted,
        "modified": min(total_added, total_deleted),
        "total": total_added + total_deleted,
    }
    logger.info(f"Churn totals: {result}")
    return result


def compute_daily_churn(repo_path: str, start_date: str, end_date: str) -> dict[str, dict[str, int]]:
    commits = get_commit_history(repo_path, start_date, end_date)

    if not commits:
        return {}

    daily: dict[str, dict[str, int]] = {}

    for commit in commits:
        day = commit["date"]
        churn = compute_commit_churn(repo_path, commit["hash"])

        if day not in daily:
            daily[day] = {"added": 0, "deleted": 0, "modified": 0, "total": 0}

        daily[day]["added"] += churn["added"]
        daily[day]["deleted"] += churn["deleted"]

    for day in daily:
        daily[day]["modified"] = min(daily[day]["added"], daily[day]["deleted"])
        daily[day]["total"] = daily[day]["added"] + daily[day]["deleted"]

    return daily


def compute_commit_churn(repo_path: str, sha: str) -> dict:
    if not os.path.isdir(repo_path):
        raise ValueError(f"Repository path does not exist: {repo_path}")

    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise ValueError(f"Not a git repository (missing .git): {repo_path}")

    output = _run_git_show(repo_path, sha)

    added, deleted = _parse_numstat(output)

    return {
        "added": added,
        "deleted": deleted,
        "modified": min(added, deleted),
        "total": added + deleted,
    }


def _run_git_show(repo_path: str, sha: str) -> str:
    cmd = [
        "git",
        "--no-pager",
        "-C",
        repo_path,
        "show",
        "--numstat",
        "--first-parent",
        "--format=",
        sha,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise ValueError(f"git show failed: {result.stderr.strip()}")

    return result.stdout


def _parse_numstat(output: str) -> tuple[int, int]:
    added = 0
    deleted = 0

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split("\t", maxsplit=2)
        if len(parts) < 3:
            continue

        a_str, d_str = parts[0], parts[1]

        if a_str == "-" or d_str == "-":
            continue

        try:
            a_val = int(a_str)
            d_val = int(d_str)
        except ValueError:
            continue

        if a_val < 0 or d_val < 0:
            continue

        added += a_val
        deleted += d_val

    return added, deleted