---
name: cih
description: Run the Continuous Improvement Harness interactively — audit a target repo and apply TDD-gated improvements via orchestrated agent teams.
---
# Continuous Improvement Harness (interactive)

You are the ORCHESTRATOR. You own pure control flow; all domain work is delegated to agents
defined in `.claude/agents/`. State lives under an absolute `state_dir` OUTSIDE the target repo.

## Inputs
- `target_repo` (absolute), `state_dir` (absolute, non-nested with target), `mode`
  (`fixed-N` with `iterations`, or `until-converged`), `focus_areas`.

## Per iteration
1. Spawn **high-planner**: audit the target (LLM read + focus_areas), update the opportunity
   ledger, and emit team charters (each with an impact manifest). Charters must not overlap on
   files.
2. For each charter (parallel teams, each in its own git **worktree** on branch
   `cih/<run_id>/iter-NNN/<team_id>`):
   - **planner** → task plan with testable acceptance criteria
   - **plan-reviewer** → approve/reject (bounded re-plan)
   - **executor** → red-green TDD commits in the worktree
   - mechanical **tdd_verifier** (pytest) → green required before review
   - **execution-reviewer** → approve/reject (bounded retry)
3. Integrate PASSED teams through the bounded **merge queue**: merge onto the live integration
   base, re-run the full suite + execution-reviewer, then advance the integration head.
4. Record `audit.json`, per-team artifacts (`plan.json`, `execution.json`, `exec_review.json`,
   `attempts.json`), and update the ledger and `run.json`.

## Termination
- `fixed-N`: stop after N iterations.
- `until-converged`: stop when the ledger is dry for `convergence_dry_streak` iterations.
- Always bounded by `max_iterations` and the budget cap.

## Safety invariants (enforced, not optional)
- NEVER `git push`. NEVER `git add -A` / `git add --all` — stage only declared files via the
  staging wrapper. `git add -a` is forbidden in production control flow.
- `target_repo` and `state_dir` are absolute and non-nested; state lives outside the target.
- Every git command is logged.
