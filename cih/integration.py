# cih/integration.py
"""Real git-backed integration layer for the orchestrator.

`build_integration` wires up a `(team_runner, integrate_fn)` pair that share an
internal `WorktreeManager` and a `pending` registry. team_runner runs each team
in its own worktree (keeping it for passed teams, removing it for failed ones)
and persists per-team artifacts. integrate_fn rebases each passing team's branch
onto the rolling base, re-runs the suite + execution-reviewer, and merges via the
merge queue, returning a MergeOutcome carrying the real rebased tip SHA.
"""
import subprocess
from pathlib import Path

from cih import merge_queue
from cih.agents import invoke
from cih.safety import GitError, run_git
from cih.state import StateHeader, write_state
from cih.team import run_team
from cih.worktree import WorktreeManager


def build_integration(*, contracts, runner, verifier, repo, worktrees_root, run_id,
                      base_sha, state_dir, plan_review_retries, exec_review_retries,
                      attempt_cap, integration_retries, log=None):
    mgr = WorktreeManager(repo, worktrees_root, run_id, log)
    state_dir = Path(state_dir)
    pending: dict[str, dict] = {}

    def _persist(iteration, team_id, result):
        iter_id = f"iter-{iteration:03d}"
        teamdir = state_dir / "iterations" / iter_id / "teams" / team_id
        status = "passed" if result.passed else "failed"

        def header():
            return StateHeader(run_id, iter_id, team_id, None, status, "team")

        write_state(teamdir / "plan.json", header(), result.plan)
        write_state(teamdir / "execution.json", header(), {"commits": result.commits})
        write_state(teamdir / "exec_review.json", header(),
                    {"passed": result.passed, "reason": result.reason})
        write_state(teamdir / "attempts.json", header(), {"attempts": result.attempts})

    def team_runner(charters, ctx):
        iteration = ctx["iteration"]
        results = []
        for charter in charters:
            team_id = charter["id"]
            wt = mgr.create(team_id, base_sha)
            result = run_team(
                charter=charter, contracts=contracts, runner=runner,
                verifier=verifier, plan_review_retries=plan_review_retries,
                exec_review_retries=exec_review_retries, attempt_cap=attempt_cap,
                base_sha=base_sha, branch=wt.branch, worktree_path=wt.path)
            _persist(iteration, team_id, result)
            if result.passed:
                pending[team_id] = {"worktree": wt, "charter": charter,
                                    "result": result}
            else:
                mgr.remove(wt)
            results.append(result)
        return results

    def integrate_fn(results, ctx):
        teams = [(tid, pending[tid]["charter"]) for tid in pending
                 if pending[tid]["result"].passed]

        def reverify(team_id, current_base):
            wt = pending[team_id]["worktree"]
            # Rebase the team branch onto the rolling base inside its worktree.
            try:
                run_git(["rebase", current_base], cwd=Path(wt.path), log=log)
            except GitError:
                try:
                    run_git(["rebase", "--abort"], cwd=Path(wt.path), log=log)
                except GitError:
                    pass
                return (False, None)
            # Full suite in the worktree (exit 5 == no tests collected, acceptable).
            proc = subprocess.run(["python", "-m", "pytest", "-q"],
                                  cwd=wt.path, capture_output=True, text=True)
            if proc.returncode not in (0, 5):
                return (False, None)
            review = invoke(runner, contracts["execution-reviewer"],
                            {"team_id": team_id, "rebased": True})
            if not review["approved"]:
                return (False, None)
            return (True, mgr.head_sha(wt))

        return merge_queue.integrate(
            teams, base_sha=base_sha, reverify=reverify,
            integration_retries=integration_retries)

    return team_runner, integrate_fn
