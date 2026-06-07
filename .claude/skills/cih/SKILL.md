---
name: cih
description: Run the Continuous Improvement Harness interactively — audit a target repo and apply TDD-gated improvements via orchestrated agent teams.
---
# Continuous Improvement Harness (interactive)

You are the ORCHESTRATOR. You own pure control flow; all domain work is delegated to agents
defined in `.claude/agents/`. State lives under an absolute `state_dir` OUTSIDE the target repo.

## Inputs
- `target_repo` (absolute) and `state_dir` (absolute, non-nested with target) are **direct
  args** — never asked in the Q&A.
- `--depth low|medium|high` controls the scoping question budget: `low`=3, `medium`=6,
  `high`=10. Default `medium`. Resolve it with `cih.config.depth_budget(name)`, which raises
  `ConfigError` on an unknown value — surface that and stop before asking anything. `--depth` governs only this scoping phase; it is never written to `run.json`.

## Scoping phase (interactive — skill only)

Runs ONCE before the loop. The headless runner (`python -m cih.runner`) does NOT do this; it
requires a complete `run.json`.

1. Resolve the question budget `B` from `--depth` (default `medium` → 6).
2. Interview the user for the **intent params only**, asking **one `AskUserQuestion` at a
   time**, multiple-choice where possible:
   - `focus_areas` — what to audit/improve in the target.
   - `mode` — `fixed-N` (then `iterations`) vs `until-converged`, plus optional
     `max_iterations` / `budget_cap`.
   - `value_threshold` — how aggressive to be (default `0.5`).
   Spend questions on what you do NOT already know from the invocation. Ask at most `B`
   questions and **stop early** as soon as every required intent param is confidently known —
   do not pad to `B`.
3. Leave every other `run.json` field at its `cih.config.RunConfig` default (retries, team
   count, cooldown, `tdd_adapter`, `convergence_dry_streak`, …). Do NOT ask about them.
4. Assemble the config via `RunConfig.create(target_repo=…, state_dir=…, mode=…, …)`. If it
   raises `ConfigError` (e.g. `fixed-N` without positive `iterations`), surface the message and
   re-ask the offending param instead of proceeding.
5. Present a summary of the assembled `run.json` (goal/focus_areas, mode + caps,
   value_threshold) and ask a **single** "go ahead?" confirmation. If the user declines, let
   them re-answer/adjust, then re-summarize. On "yes", write `run.json` and enter the loop.

After the confirmation the run is **fully autonomous** — ask no further questions until it
terminates.

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
