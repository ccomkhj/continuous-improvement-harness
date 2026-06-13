import subprocess
from pathlib import Path

from cih.worktree import WorktreeManager


def _seed_repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("hi")
    subprocess.run(["git", "add", "f.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True
    ).stdout.strip()


def test_create_worktree_on_namespaced_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _seed_repo(repo)
    wts = tmp_path / "wts"
    mgr = WorktreeManager(repo=repo, worktrees_root=wts, run_id="run-1")
    wt = mgr.create(team_id="team-01", base_sha=base)
    assert Path(wt.path).exists()
    assert (Path(wt.path) / "f.txt").read_text() == "hi"
    assert wt.branch == "cih/run-1/team-01"


def test_remove_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _seed_repo(repo)
    mgr = WorktreeManager(repo=repo, worktrees_root=tmp_path / "wts", run_id="run-1")
    wt = mgr.create(team_id="team-01", base_sha=base)
    mgr.remove(wt)
    assert not Path(wt.path).exists()


def test_head_sha_reflects_commits_in_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _seed_repo(repo)
    mgr = WorktreeManager(repo=repo, worktrees_root=tmp_path / "wts", run_id="run-1")
    wt = mgr.create(team_id="team-01", base_sha=base)
    (Path(wt.path) / "g.txt").write_text("new")
    subprocess.run(["git", "add", "g.txt"], cwd=wt.path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add g"], cwd=wt.path, check=True)
    assert mgr.head_sha(wt) != base
