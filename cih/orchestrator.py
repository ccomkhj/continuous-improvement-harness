# cih/orchestrator.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from cih.config import RunConfig
from cih.state import StateHeader, write_state, read_state
from cih.ledger import Ledger, Opportunity, fingerprint
from cih.merge_queue import MergeOutcome

@dataclass
class IterationResult:
    iteration: int
    charters: list = field(default_factory=list)
    team_results: list = field(default_factory=list)
    dry: bool = False

class Orchestrator:
    def __init__(self, cfg: RunConfig, high_planner_fn: Callable,
                 team_runner_fn: Callable, integrate_fn: Optional[Callable] = None,
                 run_id: str = "run-1", on_iteration_end: Optional[Callable] = None):
        self.cfg = cfg
        self.high_planner_fn = high_planner_fn
        self.team_runner_fn = team_runner_fn
        self.integrate_fn = integrate_fn or (lambda results, ctx: MergeOutcome())
        self.run_id = run_id
        self.on_iteration_end = on_iteration_end
        self.state_dir = Path(cfg.state_dir)
        led_path = self.state_dir / "ledger.json"
        self.ledger = (Ledger.from_dict(read_state(led_path)["body"])
                       if led_path.exists() else Ledger())

    def _ingest_opportunities(self, audit: dict) -> None:
        for o in audit.get("opportunities", []):
            self.ledger.upsert(Opportunity(
                fp=fingerprint(o["title"], o["scope"]), title=o["title"],
                scope=o["scope"], value=o["value"], confidence=o["confidence"],
                effort=o["effort"], risk=o["risk"], rationale=o["rationale"]))

    def _persist_run(self, status: str, body: dict) -> None:
        write_state(self.state_dir / "run.json",
                    StateHeader(self.run_id, None, None, None, status, "orchestrator"),
                    body)

    def _persist_ledger(self, status: str) -> None:
        write_state(self.state_dir / "ledger.json",
                    StateHeader(self.run_id, None, None, None, status, "orchestrator"),
                    self.ledger.to_dict())

    def _fire_iteration_end(self) -> None:
        if self.on_iteration_end is None:
            return
        try:
            self.on_iteration_end()
        except Exception as e:  # best-effort: never abort the run
            from cih.progress import append_progress
            append_progress(self.state_dir, f"on_iteration_end callback failed: {e}")

    def run(self) -> dict:
        iterations_run = 0
        teams_run = 0
        dry_streak = 0
        stopped_reason = "completed"
        iteration_results: list[IterationResult] = []
        self._persist_run("in_progress", self.cfg.to_dict())

        try:
            while True:
                if self.cfg.mode == "fixed-N":
                    if iterations_run >= self.cfg.iterations:
                        stopped_reason = "completed"
                        break
                if iterations_run >= self.cfg.max_iterations:
                    stopped_reason = "max_iterations"
                    break
                if self.cfg.budget_cap is not None and teams_run >= self.cfg.budget_cap:
                    stopped_reason = "budget_exhausted"
                    break

                i = iterations_run + 1
                ctx = {"iteration": i, "target_repo": self.cfg.target_repo,
                       "focus_areas": self.cfg.focus_areas,
                       "ledger": self.ledger.to_dict()}
                audit = self.high_planner_fn(ctx)
                self._ingest_opportunities(audit)

                charters = audit.get("charters", [])[: self.cfg.max_teams_per_iteration]
                if self.cfg.budget_cap is not None:
                    charters = charters[: max(0, self.cfg.budget_cap - teams_run)]
                results = self.team_runner_fn(charters, ctx)
                if self.cfg.budget_cap is not None:
                    teams_run += len(charters)
                outcome = self.integrate_fn(results, ctx)

                # mark the ledger from the integration outcome (drives convergence)
                fp_by_team = {c["id"]: c["opportunity_fp"]
                              for c in charters if c.get("opportunity_fp")}

                def ledger_fp(team_id):
                    fp = fp_by_team.get(team_id)
                    return fp if fp and self.ledger.get(fp) else None

                for tid in outcome.merged:
                    fp = ledger_fp(tid)
                    if fp:
                        self.ledger.mark_merged(fp)
                for tid in outcome.rejected:
                    fp = ledger_fp(tid)
                    if fp:
                        self.ledger.record_attempt_failure(
                            fp, current_iteration=i,
                            cooldown_iterations=self.cfg.cooldown_iterations,
                            max_attempts=self.cfg.opportunity_max_attempts)

                iterations_run = i

                dry = self.ledger.is_dry(self.cfg.value_threshold, current_iteration=i)
                dry_streak = dry_streak + 1 if dry else 0
                iteration_results.append(IterationResult(
                    iteration=i, charters=charters, team_results=results, dry=dry))

                iter_dir = self.state_dir / "iterations" / f"iter-{i:03d}"
                iter_header = StateHeader(self.run_id, f"iter-{i:03d}", None, None,
                                          "open", "orchestrator")
                write_state(iter_dir / "audit.json", iter_header, audit)

                # spec §10 observability artifacts (orchestrator-owned)
                merged_set, rejected_set = set(outcome.merged), set(outcome.rejected)
                teams_body = {
                    "charters": charters,
                    "results": [
                        {"team_id": getattr(r, "team_id", None),
                         "passed": getattr(r, "passed", None),
                         "reason": getattr(r, "reason", ""),
                         "merged": getattr(r, "team_id", None) in merged_set,
                         "rejected": getattr(r, "team_id", None) in rejected_set}
                        for r in results
                    ],
                    "dry": dry,
                }
                write_state(iter_dir / "teams.json", iter_header, teams_body)

                iter_dir.mkdir(parents=True, exist_ok=True)
                lines = [f"# Iteration {i}", "",
                         f"- charters dispatched: {len(charters)}",
                         f"- merged: {sorted(merged_set)}",
                         f"- rejected: {sorted(rejected_set)}",
                         f"- dry: {dry}", ""]
                (iter_dir / "iteration.md").write_text("\n".join(lines))

                self._persist_ledger("in_progress")
                self._fire_iteration_end()

                if self.cfg.mode == "until-converged" and dry_streak >= self.cfg.convergence_dry_streak:
                    stopped_reason = "converged"
                    break
        except BaseException as e:
            summary = {"iterations_run": iterations_run, "stopped_reason": "failed",
                       "error": f"{type(e).__name__}: {e}",
                       "iterations": len(iteration_results)}
            self._persist_run("failed", {"config": self.cfg.to_dict(), "summary": summary})
            self._persist_ledger("failed")
            raise

        summary = {"iterations_run": iterations_run, "stopped_reason": stopped_reason,
                   "iterations": len(iteration_results)}
        self._persist_run("done", {"config": self.cfg.to_dict(), "summary": summary})
        self._persist_ledger("done")
        # Final fire AFTER the done persist so the report renders against the
        # terminal state (done badge, no meta-refresh). The per-iteration fires
        # above run against in_progress for live mid-run updates. Never fired in
        # the crash/except branch.
        self._fire_iteration_end()
        # Success path only: prune worktree dirs (keeping branch refs). A crashed
        # run (the except branch above) intentionally KEEPS its worktrees for
        # resume/post-mortem and never reaches here.
        td = getattr(self.integrate_fn, "teardown", None)
        if td:
            td()
        return summary

def reconcile(cfg: RunConfig, run_id: str) -> dict:
    """Compare persisted state against git ground truth before resuming (spec §10)."""
    import json
    from cih.safety import run_git, GitError

    issues = []
    state_dir = Path(cfg.state_dir)
    target_repo = Path(cfg.target_repo)
    if not (state_dir / "run.json").exists():
        issues.append("run.json missing")
    elif not (state_dir / "ledger.json").exists():
        issues.append("ledger.json missing")
    if not target_repo.exists():
        issues.append("target_repo missing")

    # Ground-truth git checks per persisted team. Skipped if the repo is absent.
    if target_repo.exists():
        for exec_path in sorted(state_dir.glob("iterations/*/teams/*/execution.json")):
            team_id = exec_path.parent.name
            # branches are iteration-scoped: cih/<run_id>/iter-NNN/<team_id>
            iter_id = exec_path.parent.parent.parent.name
            branch = f"cih/{run_id}/{iter_id}/{team_id}"
            try:
                doc = json.loads(exec_path.read_text())
            except (json.JSONDecodeError, OSError):
                issues.append(f"execution.json unreadable for {team_id}")
                continue
            # A team rejected by the execution-reviewer persists status="failed"
            # and has its branch/worktree intentionally pruned — not an issue.
            if doc.get("status") == "failed":
                continue
            try:
                run_git(["rev-parse", "--verify", branch], cwd=target_repo)
            except GitError:
                issues.append(f"branch {branch} missing")
            body = doc.get("body", {})
            head_sha = body.get("head_sha")
            if head_sha:
                try:
                    run_git(["cat-file", "-e", f"{head_sha}^{{commit}}"], cwd=target_repo)
                except GitError:
                    issues.append(f"head_sha {head_sha} missing ({team_id})")
            for commit in body.get("commits", []):
                for key in ("red_sha", "green_sha"):
                    sha = commit.get(key)
                    if not sha:
                        continue
                    try:
                        run_git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=target_repo)
                    except GitError:
                        issues.append(f"commit {sha} missing ({team_id} {key})")

    return {"resumable": not issues, "issues": issues}
