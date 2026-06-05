# cih/orchestrator.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from cih.config import RunConfig
from cih.state import StateHeader, write_state
from cih.ledger import Ledger, Opportunity, fingerprint

@dataclass
class IterationResult:
    iteration: int
    charters: list = field(default_factory=list)
    team_results: list = field(default_factory=list)
    dry: bool = False

class Orchestrator:
    def __init__(self, cfg: RunConfig, high_planner_fn: Callable,
                 team_runner_fn: Callable, run_id: str = "run-1"):
        self.cfg = cfg
        self.high_planner_fn = high_planner_fn
        self.team_runner_fn = team_runner_fn
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
            self.team_runner_fn(charters, ctx)  # integration handled inside in real wiring
            iterations_run = i

            dry = self.ledger.is_dry(self.cfg.value_threshold, current_iteration=i)
            dry_streak = dry_streak + 1 if dry else 0

            iter_dir = self.state_dir / "iterations" / f"iter-{i:03d}"
            write_state(iter_dir / "audit.json",
                        StateHeader(self.run_id, f"iter-{i:03d}", None, None,
                                    "open", "orchestrator"), audit)

            if self.cfg.mode == "until-converged" and dry_streak >= self.cfg.convergence_dry_streak:
                stopped_reason = "converged"
                break

        summary = {"iterations_run": iterations_run, "stopped_reason": stopped_reason}
        self._persist_run("done", {"config": self.cfg.to_dict(), "summary": summary})
        return summary
