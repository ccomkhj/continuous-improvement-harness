from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cih.safety import GitError, run_git


@dataclass
class Worktree:
    team_id: str
    path: str
    branch: str
    base_sha: str


class WorktreeManager:
    def __init__(
        self,
        repo: Path,
        worktrees_root: Path,
        run_id: str,
        log: Callable[[str], None] | None = None,
    ):
        self.repo = Path(repo)
        self.worktrees_root = Path(worktrees_root)
        self.run_id = run_id
        self.log = log

    def create(self, team_id: str, base_sha: str) -> Worktree:
        branch = f"cih/{self.run_id}/{team_id}"
        path = self.worktrees_root / self.run_id / team_id
        path.parent.mkdir(parents=True, exist_ok=True)
        run_git(["worktree", "add", "-b", branch, str(path), base_sha], cwd=self.repo, log=self.log)
        return Worktree(team_id=team_id, path=str(path), branch=branch, base_sha=base_sha)

    def head_sha(self, wt: Worktree) -> str:
        return run_git(["rev-parse", "HEAD"], cwd=Path(wt.path), log=self.log).strip()

    def remove(self, wt: Worktree) -> None:
        run_git(["worktree", "remove", "--force", wt.path], cwd=self.repo, log=self.log)
        # best-effort branch cleanup
        try:
            run_git(["branch", "-D", wt.branch], cwd=self.repo, log=self.log)
        except GitError:
            if self.log:
                self.log(f"worktree branch cleanup failed (leaked): {wt.branch}")
