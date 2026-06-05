# tests/test_safety.py
import subprocess
import pytest
from pathlib import Path
from cih.safety import run_git, GitError, forbidden_paths, validate_no_forbidden

def _init_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)

def test_run_git_logs_command(tmp_path):
    _init_repo(tmp_path)
    log = []
    out = run_git(["rev-parse", "--is-inside-work-tree"], cwd=tmp_path, log=log.append)
    assert out.strip() == "true"
    assert any("rev-parse" in line for line in log)

def test_run_git_raises_on_failure(tmp_path):
    _init_repo(tmp_path)
    with pytest.raises(GitError):
        run_git(["checkout", "does-not-exist"], cwd=tmp_path)

def test_validate_no_forbidden_blocks_harness_paths():
    bad = ["src/app.py", ".cih/run.json"]
    with pytest.raises(GitError):
        validate_no_forbidden(bad, forbidden_paths())

def test_validate_no_forbidden_allows_clean_paths():
    validate_no_forbidden(["src/app.py", "tests/test_app.py"], forbidden_paths())
