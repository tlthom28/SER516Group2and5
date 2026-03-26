import os
import tempfile
import shutil
import pytest
from src.core.git_clone import GitRepoCloner, GitCloneError

def test_clone_local_repo(tmp_path):
    #create a fake local git repo
    repo_dir = tmp_path / "fake_repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Test Repo\n")
    # Test
    cloner = GitRepoCloner()
    cloned_path = cloner.clone(str(repo_dir))
    assert os.path.exists(cloned_path)
    assert os.path.isfile(os.path.join(cloned_path, "README.md"))
    cloner.cleanup()
    assert not os.path.exists(cloner.temp_dir or "")

def test_cleanup_removes_temp_dir(tmp_path):
    cloner = GitRepoCloner()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    cloned_path = cloner.clone(str(repo_dir))
    cloner.cleanup()
    assert cloner.temp_dir is None or not os.path.exists(cloner.temp_dir)

def test_clone_invalid_url():
    cloner = GitRepoCloner()
    # Use a non-routable host so git fails fast without prompting for credentials
    with pytest.raises(GitCloneError):
        cloner.clone("https://invalid.invalid/no-such/repo.git")
    cloner.cleanup()

def test_clone_valid_public_repo(monkeypatch):
    cloner = GitRepoCloner()
    repo_url = "https://github.com/octocat/Hello-World"
    # Patch subprocess.run to simulate a successful clone
    def fake_run(args, capture_output=False, text=False, timeout=None, env=None):
        dest = args[-1]
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "README.md"), "w") as f:
            f.write("# Hello World\n")
        return type("Result", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr("subprocess.run", fake_run)
    cloned_path = cloner.clone(repo_url)
    assert os.path.exists(cloned_path)
    assert os.path.isfile(os.path.join(cloned_path, "README.md"))
    cloner.cleanup()