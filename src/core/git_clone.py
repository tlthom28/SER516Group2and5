import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, date, timedelta
from typing import Optional

logger = logging.getLogger("repopulse.core.git_clone")


class GitCloneError(Exception):
    pass


class GitRepoCloner:
    def __init__(self):
        self.temp_dir: Optional[str] = None
        self.cloned_at: Optional[str] = None
        self.commit_hash: Optional[str] = None

    def clone(self, repo_url_or_path: str, shallow: bool = True) -> str:
        """Clone a GitHub repo (or copy a local dir) into a temp directory.
        Returns the path to the cloned repo. Raises GitCloneError on failure."""
        self.temp_dir = tempfile.mkdtemp(prefix="repopulse_clone_")
        self.cloned_at = datetime.utcnow().isoformat()
        try:
            dest_path = os.path.join(self.temp_dir, os.path.basename(repo_url_or_path))
            if os.path.isdir(repo_url_or_path):
                shutil.copytree(
                    repo_url_or_path,
                    dest_path,
                    dirs_exist_ok=True
                )
                self.commit_hash = self.get_commit_hash(dest_path)
                return dest_path
            else:
                dest = os.path.join(self.temp_dir, "repo")
                env = os.environ.copy()
                env["GIT_TERMINAL_PROMPT"] = "0"
                cmd = ["git", "clone"]
                if shallow:
                    cmd += ["--depth", "1"]
                cmd += [repo_url_or_path, dest]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120, env=env,
                )
                if result.returncode != 0:
                    raise GitCloneError(f"Git clone failed: {result.stderr.strip()}")
                self.commit_hash = self.get_commit_hash(dest)
                logger.info(f"Cloned repository @ commit {self.commit_hash[:8] if self.commit_hash else 'unknown'}")
                return dest
        except GitCloneError:
            self.cleanup()
            raise
        except Exception as e:
            self.cleanup()
            raise GitCloneError(f"Failed to clone repo: {e}")

    def deepen_since(self, repo_path: str, since_date: str) -> None:
        """Fetch additional history into a shallow clone back to since_date.

        Runs ``git fetch --shallow-since=<date> origin`` so that commits
        from *since_date* onwards become available for log / diff operations
        without downloading the entire repository history.
        """
        fetch_since = _history_fetch_since_date(since_date)
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        cmd = [
            "git", "-C", repo_path,
            "fetch", "--shallow-since", fetch_since, "origin",
        ]
        logger.info(
            "Deepening clone since %s (requested start %s)",
            fetch_since,
            since_date,
        )
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, env=env,
            )
            if result.returncode != 0:
                logger.warning(f"git fetch --shallow-since failed: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            logger.warning("git fetch --shallow-since timed out")
        except Exception as e:
            logger.warning(f"Failed to deepen clone: {e}")

    @staticmethod
    def get_commit_hash(repo_path: str) -> Optional[str]:
        """Extract the current HEAD commit hash from a Git repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.warning(f"Failed to get commit hash from {repo_path}: {result.stderr}")
                return None
        except Exception as e:
            logger.warning(f"Error extracting commit hash: {e}")
            return None

    @staticmethod
    def get_commit_timestamp(repo_path: str, commit_hash: Optional[str] = None) -> Optional[str]:
        """Extract the timestamp of a specific commit or HEAD if not provided."""
        try:
            ref = commit_hash or "HEAD"
            result = subprocess.run(
                ["git", "log", "-1", "--format=%aI", ref],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.warning(f"Failed to get commit timestamp: {result.stderr}")
                return None
        except Exception as e:
            logger.warning(f"Error extracting commit timestamp: {e}")
            return None

    def cleanup(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            self.temp_dir = None


def _history_fetch_since_date(since_date: str) -> str:
    """Fetch one extra day of history so boundary commits have parents.

    Churn uses ``git show --numstat`` per commit. With a shallow clone fetched
    starting exactly at the requested date, the first in-range commit may be a
    shallow boundary whose parent is missing, causing Git to report the entire
    file contents as additions. Pulling one extra day of history keeps the diff
    for the boundary commit anchored to its real parent in common cases.
    """
    try:
        parsed = date.fromisoformat(since_date)
    except ValueError:
        return since_date
    return (parsed - timedelta(days=1)).isoformat()
