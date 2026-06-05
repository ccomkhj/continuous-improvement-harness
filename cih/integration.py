# cih/integration.py
"""Real git-backed integration layer for the orchestrator.

`build_integration` wires up a `(team_runner, integrate_fn)` pair that share an
internal `WorktreeManager`, a mutable integration `head`, and a per-iteration
`pending` registry. team_runner runs each team in its own iteration-scoped
worktree (branched off the CURRENT integration head), keeping it for passed
teams and removing it for failed/crashed ones, and persists per-team artifacts.

integrate_fn MERGES each passing team's branch into a single, advancing
integration worktree/branch (`cih/<run_id>/integration`), re-runs the suite +
execution-reviewer there, and threads the rolling tip via the merge queue.
Using merge (not rebase) preserves the executor commit SHAs so `reconcile` can
still resolve them, and lets iteration N+1 build on iteration N's merged result.
"""
import functools
import subprocess
from pathlib import Path

from cih import merge_queue
from cih.agents import invoke
from cih.safety import GitError, run_git
from cih.state import StateHeader, write_state
from cih.tdd_verifier import verify_tdd
from cih.team import TeamResult, run_team
from cih.worktree import WorktreeManager


def build_integration(*, contracts, runner, verifier=None, repo, worktrees_root, run_id,
                      base_sha, state_dir, plan_review_retries, exec_review_retries,
                      attempt_cap, integration_retries, tdd_adapter="pytest", log=None):
    mgr = WorktreeManager(repo, worktrees_root, run_id, log)
    repo = Path(repo)
    worktrees_root = Path(worktrees_root)
    state_dir = Path(state_dir)
    pending: dict[str, dict] = {}

    # Mutable integration state, advances across iterations so improvements compound.
    int_branch = f"cih/{run_id}/integration"
    state = {"head": base_sha, "int_wt": None}

    def _ensure_int_wt():
        if state["int_wt"] is None:
            int_wt = worktrees_root / run_id / "integration"
            int_wt.parent.mkdir(parents=True, exist_ok=True)
            run_git(["worktree", "add", "-b", int_branch, str(int_wt), state["head"]],
                    cwd=repo, log=log)
            state["int_wt"] = int_wt
        return state["int_wt"]

    def _persist(iteration, team_id, result, wt=None):
        iter_id = f"iter-{iteration:03d}"
        teamdir = state_dir / "iterations" / iter_id / "teams" / team_id
        status = "passed" if result.passed else "failed"

        def header():
            return StateHeader(run_id, iter_id, team_id, None, status, "team")

        body = {"commits": result.commits}
        if wt is not None:
            body["branch"] = wt.branch
            try:
                body["head_sha"] = mgr.head_sha(wt)
            except GitError:
                body["head_sha"] = None
        write_state(teamdir / "plan.json", header(), result.plan)
        write_state(teamdir / "execution.json", header(), body)
        write_state(teamdir / "exec_review.json", header(),
                    {"passed": result.passed, "reason": result.reason})
        write_state(teamdir / "attempts.json", header(), {"attempts": result.attempts})

    def team_runner(charters, ctx):
        iteration = ctx["iteration"]
        iter_id = f"iter-{iteration:03d}"
        # Reset pending so integrate_fn only ever processes THIS iteration's teams.
        pending.clear()
        results = []
        for charter in charters:
            team_id = charter["id"]
            # Iteration-scoped worktree/branch: cih/<run_id>/iter-NNN/<team_id>.
            # Branch off the CURRENT integration head so teams build on prior merges.
            wt = mgr.create(f"{iter_id}/{team_id}", state["head"])
            # When no explicit verifier is injected (production), bind a real
            # mechanical TDD verifier to THIS team's worktree path.
            team_verifier = verifier
            if team_verifier is None:
                team_verifier = functools.partial(
                    verify_tdd, repo=wt.path, adapter=tdd_adapter)
            try:
                result = run_team(
                    charter=charter, contracts=contracts, runner=runner,
                    verifier=team_verifier, plan_review_retries=plan_review_retries,
                    exec_review_retries=exec_review_retries, attempt_cap=attempt_cap,
                    base_sha=state["head"], branch=wt.branch, worktree_path=wt.path)
            except Exception as e:  # don't leak the worktree on an unexpected crash
                mgr.remove(wt)
                result = TeamResult(team_id, False, f"team crashed: {e}")
                _persist(iteration, team_id, result)
                results.append(result)
                continue
            _persist(iteration, team_id, result, wt=wt)
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
        if not teams:
            return merge_queue.MergeOutcome(final_base_sha=state["head"])

        int_wt = _ensure_int_wt()
        base = state["head"]

        def reverify(team_id, current_base):
            # Operate on the single advancing integration worktree. We merge into
            # the integration branch (which already advanced past prior merges);
            # current_base is bookkeeping only — the actual merge target is the
            # integration HEAD. On any rejection we reset back to `base`.
            team_branch = pending[team_id]["worktree"].branch
            try:
                run_git(["merge", "--no-ff", "--no-edit", team_branch],
                        cwd=int_wt, log=log)
            except GitError:  # merge conflict
                try:
                    run_git(["merge", "--abort"], cwd=int_wt, log=log)
                except GitError:
                    pass
                return (False, None)

            def _reject():
                run_git(["reset", "--hard", base], cwd=int_wt, log=log)
                return (False, None)

            # Full suite in the integration worktree (exit 5 == no tests, ok).
            proc = subprocess.run(["python", "-m", "pytest", "-q"],
                                  cwd=int_wt, capture_output=True, text=True)
            if proc.returncode not in (0, 5):
                return _reject()
            review = invoke(runner, contracts["execution-reviewer"],
                            {"team_id": team_id, "merged": True})
            if not review["approved"]:
                return _reject()
            return (True, run_git(["rev-parse", "HEAD"], cwd=int_wt, log=log).strip())

        # integration_retries=0: an in-call retry of a deterministic merge is a
        # no-op. Cross-iteration recovery happens via the orchestrator ledger
        # cooldown -> reopen, which re-runs a FRESH executor against the new base
        # next iteration — that IS "re-execute against a new base" at iteration
        # granularity.
        outcome = merge_queue.integrate(
            teams, base_sha=base, reverify=reverify, integration_retries=0)

        if outcome.merged:
            state["head"] = outcome.final_base_sha
            # Belt-and-suspenders: the integration worktree branch already points
            # here; keep the stable ref in sync for reconcile/resume.
            run_git(["update-ref", f"refs/heads/{int_branch}", state["head"]],
                    cwd=repo, log=log)
        return outcome

    return team_runner, integrate_fn
