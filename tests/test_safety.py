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

def test_validate_no_forbidden_blocks_top_level_secrets():
    with pytest.raises(GitError):
        validate_no_forbidden(["secrets/key.txt"], forbidden_paths())

def test_validate_no_forbidden_blocks_traversal():
    with pytest.raises(GitError):
        validate_no_forbidden(["../outside.py"], forbidden_paths())

def test_validate_no_forbidden_blocks_absolute():
    with pytest.raises(GitError):
        validate_no_forbidden(["/etc/passwd"], forbidden_paths())

def test_validate_no_forbidden_allows_normal_src():
    validate_no_forbidden(["src/app.py"], forbidden_paths())

def _committed_repo(path: Path):
    _init_repo(path)
    (path / "a.py").write_text("a")
    subprocess.run(["git", "add", "--", "a.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)

def test_run_git_blocks_push(tmp_path):
    _init_repo(tmp_path)
    with pytest.raises(GitError) as exc:
        run_git(["push", "origin", "main"], cwd=tmp_path)
    assert "push" in str(exc.value)

def test_run_git_blocks_remote(tmp_path):
    _init_repo(tmp_path)
    with pytest.raises(GitError):
        run_git(["remote", "add", "origin", "x"], cwd=tmp_path)

def test_run_git_blocks_add_dash_A(tmp_path):
    _init_repo(tmp_path)
    with pytest.raises(GitError):
        run_git(["add", "-A"], cwd=tmp_path)

def test_run_git_blocks_add_all(tmp_path):
    _init_repo(tmp_path)
    with pytest.raises(GitError):
        run_git(["add", "--all"], cwd=tmp_path)

def test_run_git_blocks_add_dot(tmp_path):
    _init_repo(tmp_path)
    with pytest.raises(GitError):
        run_git(["add", "."], cwd=tmp_path)

def test_run_git_allows_add_explicit_pathspec(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a")
    run_git(["add", "--", "a.py"], cwd=tmp_path)
    staged = run_git(["diff", "--cached", "--name-only"], cwd=tmp_path)
    assert staged.split() == ["a.py"]

def test_run_git_allows_rev_parse(tmp_path):
    _committed_repo(tmp_path)
    out = run_git(["rev-parse", "HEAD"], cwd=tmp_path)
    assert out.strip()
