---
name: cih
description: Run the Continuous Improvement Harness interactively — clarify the goal for a target repo, then hand the TDD-gated improvement run off to a fresh Superset workspace.
argument-hint: "[--depth low|medium|high] [--target-repo <abs>] [--state-dir <abs>]"
---
# Continuous Improvement Harness (interactive)

You drive the **interactive front end**. Your job is two steps: (1) clarify the run's goal with
the user, then (2) hand the autonomous run off to a **fresh Superset workspace** that runs it
headless. You do NOT run the improvement loop in this session — once the workspace is launched,
the headless runner (`python -m cih.runner`) owns the loop. State lives under an absolute
`state_dir` OUTSIDE the target repo.

## Inputs (all inferred — flags only to override)

Triggered bare (`/cih`), infer everything from the Superset workspace env + git; never ask for
these in the Q&A. Surface the inferred values in the scoping summary so the user confirms them.
- **`target_repo`** — the current repo: `$SUPERSET_ROOT_PATH`, else `git rev-parse
  --show-toplevel`. Override with `--target-repo <abs>`.
- **`state_dir`** — `$SUPERSET_HOME_DIR/cih-state/<basename target_repo>` (e.g.
  `~/.superset/cih-state/voidsapi`); `mkdir -p` it. Reused across runs, so the opportunity
  ledger persists (until-converged remembers what was tried/cooled-down). Override with
  `--state-dir <abs>`. Must be absolute and non-nested with `target_repo`.
- **Superset project** — the current workspace's project: look up `$SUPERSET_WORKSPACE_ID` in
  `superset workspaces list --json` and read its `projectId`. Fallback: the `projects list`
  entry whose `path` resolves to `target_repo`.
- If run outside Superset and not in a git repo, nothing can be inferred — require
  `--target-repo` (derive `state_dir` from it) before proceeding.
- `--depth low|medium|high` controls the scoping question budget: `low`=3, `medium`=6,
  `high`=10. Default `medium`. Resolve it with `cih.config.depth_budget(name)`, which raises
  `ConfigError` on an unknown value — surface that and stop before asking anything. `--depth`
  governs only this scoping phase; it is never written to `run.json`.

## Scoping phase (interactive — this session only)

Runs ONCE, here. The headless runner does NOT do this; it consumes the `run.json` you produce.

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
4. Present a summary that includes both the **inferred inputs** (target_repo, Superset project,
   state_dir) and the **scoped run** (goal/focus_areas, mode + caps, value_threshold), and ask a
   **single** "go ahead?" confirmation — e.g. "Target: voidsapi · State:
   ~/.superset/cih-state/voidsapi · until-converged, focus tests+perf — go ahead?". If the user
   declines, let them adjust (including the inferred inputs), then re-summarize. On "yes",
   proceed to **Hand-off**.

## Hand-off (on "go ahead?")

After confirmation the run is **fully autonomous** — do these steps, then STOP. Ask no further
questions and do not drive the loop in this session.

1. **Resolve the cih entrypoint as an absolute path:** `CIH="$(command -v cih)"`. This matters —
   the new workspace's shell `python`/`python3` is the **system** interpreter, which does NOT
   have `cih-agent`; a bare `python -m cih.runner` there fails with `ModuleNotFoundError`. The
   absolute console script carries its own interpreter, so it runs anywhere on this host. If
   `CIH` is empty, stop and tell the user to install it (`pipx install cih-agent`).
2. **Write `run.json`** — `mkdir -p` the state_dir, then serialise the scoped config via the
   runner (do NOT hand-craft JSON):
   ```
   mkdir -p <state_dir>
   "$CIH" write-run-json \
     --mode <fixed-N|until-converged> [--iterations N] [--max-iterations M] \
     --value-threshold <x> [--focus <a> --focus <b> …] \
     --target-repo <target_repo> --state-dir <state_dir>
   ```
   This validates the config and writes `<state_dir>/run.json` — the hand-off artifact. On a
   `ConfigError` (e.g. `fixed-N` without positive `iterations`), surface the message and re-ask
   the offending param instead of proceeding.
3. **Project id** — the one resolved in Inputs (the current workspace's `projectId`, looked up
   from `$SUPERSET_WORKSPACE_ID` in `superset workspaces list --json`; path-match fallback). If
   nothing resolves, stop and tell the user to `superset projects setup` the repo first.
4. **Create a fresh workspace** that runs the loop headless against its own pristine checkout:
   ```
   superset workspaces create --local \
     --project <project_id> \
     --name "cih/<run_slug>" --branch "cih/<run_slug>" \
     --command "$CIH --from-run-json <state_dir>/run.json --target-repo \"\$PWD\""
   ```
   - `$CIH` (the absolute path from step 1) expands **now**, in this session. `\"\$PWD\"` stays
     literal so the **workspace** shell expands it to the fresh checkout root — the run targets
     that clean checkout, not your live, possibly-dirty working copy, whose untracked files
     would otherwise trip the runner's clean-tree preflight. `state_dir` and all scoped intent
     come from `run.json`.
   - Pick a unique `<run_slug>` per run (e.g. a focus-area slug + short date) so branches don't
     collide with earlier runs. No `--agent`: the run is headless, with no agent in the loop.
5. **Open and report.** `superset workspaces open <new_workspace_id>` to surface it, then report
   the workspace id / deep link to the user and STOP.

## What the autonomous run does (headless runner, in the new workspace)

### Per iteration
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

### Termination
- `fixed-N`: stop after N iterations.
- `until-converged`: stop when the ledger is dry for `convergence_dry_streak` iterations.
- Always bounded by `max_iterations` and the budget cap.

## Safety invariants (enforced, not optional)
- NEVER `git push`. NEVER `git add -A` / `git add --all` — stage only declared files via the
  staging wrapper. `git add -a` is forbidden in production control flow.
- `target_repo` and `state_dir` are absolute and non-nested; state lives outside the target.
- All work happens in disposable worktrees; the target's working tree is never touched.
- Every git command is logged.
