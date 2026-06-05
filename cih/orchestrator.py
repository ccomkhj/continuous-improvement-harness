# cih/orchestrator.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from cih.config import RunConfig
from cih.state import StateHeader, write_state
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
                 run_id: str = "run-1"):
        self.cfg = cfg
        self.high_planner_fn = high_planner_fn
        self.team_runner_fn = team_runner_fn
        self.integrate_fn = integrate_fn or (lambda results, ctx: MergeOutcome())
        self.run_id = run_id
        self.ledger = Ledger()
        self.state_dir = Path(cfg.state_dir)

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

    def run(self) -> dict:
        iterations_run = 0
        dry_streak = 0
        stopped_reason = "completed"
        iteration_results: list[IterationResult] = []
        self._persist_run("in_progress", self.cfg.to_dict())

        while True:
            if self.cfg.mode == "fixed-N":
                if iterations_run >= self.cfg.iterations:
                    stopped_reason = "completed"
                    break
            if iterations_run >= self.cfg.max_iterations:
                stopped_reason = "max_iterations"
                break

            i = iterations_run + 1
            ctx = {"iteration": i, "target_repo": self.cfg.target_repo,
                   "focus_areas": self.cfg.focus_areas,
                   "ledger": self.ledger.to_dict()}
            audit = self.high_planner_fn(ctx)
            self._ingest_opportunities(audit)

            charters = audit.get("charters", [])[: self.cfg.max_teams_per_iteration]
            results = self.team_runner_fn(charters, ctx)
            outcome = self.integrate_fn(results, ctx)

            # mark the ledger from the integration outcome (drives convergence)
            fp_by_team = {c["id"]: c["opportunity_fp"]
                          for c in charters if c.get("opportunity_fp")}
            for tid in outcome.merged:
                fp = fp_by_team.get(tid)
                if fp and self.ledger.get(fp):
                    self.ledger.mark_merged(fp)
            for tid in outcome.rejected:
                fp = fp_by_team.get(tid)
                if fp and self.ledger.get(fp):
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
            write_state(iter_dir / "audit.json",
                        StateHeader(self.run_id, f"iter-{i:03d}", None, None,
                                    "open", "orchestrator"), audit)

            if self.cfg.mode == "until-converged" and dry_streak >= self.cfg.convergence_dry_streak:
                stopped_reason = "converged"
                break

        summary = {"iterations_run": iterations_run, "stopped_reason": stopped_reason,
                   "iterations": len(iteration_results)}
        self._persist_run("done", {"config": self.cfg.to_dict(), "summary": summary})
        return summary

def reconcile(cfg: RunConfig, run_id: str) -> dict:
    """Compare persisted state against ground truth before resuming."""
    issues = []
    state_dir = Path(cfg.state_dir)
    run_json = state_dir / "run.json"
    if not run_json.exists():
        issues.append("run.json missing")
    if not Path(cfg.target_repo).exists():
        issues.append("target_repo missing")
    return {"resumable": not issues, "issues": issues}
