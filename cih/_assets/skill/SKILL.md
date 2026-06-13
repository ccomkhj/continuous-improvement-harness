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

## At a glance

```
(1) Scope  — interview the user, synthesize a brief  ──►  writes run.json
(2) Hand off — spawn a fresh workspace running the loop headless + a watcher  ──►  STOP
```

Two phases, run **once** in this session, then you stop. The headless runner consumes `run.json`
and owns everything after the hand-off — read the detailed sections below before acting.

| Input | Default / how it's inferred | Override |
|-------|-----------------------------|----------|
| `target_repo` | `$SUPERSET_ROOT_PATH`, else `git rev-parse --show-toplevel` | `--target-repo <abs>` |
| `state_dir` | `$SUPERSET_HOME_DIR/cih-state/<basename target_repo>` (outside the repo, reused across runs) | `--state-dir <abs>` |
| Superset project | `projectId` of `$SUPERSET_WORKSPACE_ID`; else path-match in `projects list` | — |
| `--depth` | question budget: low=3, medium=6 (default), high=10; scoping-only, never in `run.json` | `--depth <level>` |

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
An autonomous run is expensive and runs unattended — **invest in rigorous, specific questions
so you understand the run fully before launching.** Surface params alone (three quick questions)
are NOT enough; under-scoping wastes a long run on the wrong thing.

0. **Ground yourself first — never ask blind.** Read the repo's top-level layout, test setup
   (`pyproject.toml`/`tox`/CI), and any benchmark/lint config; skim the areas the user names.
   Use what you learn to make every question concrete and repo-specific (offer the *real* module
   names and *real* candidate hotspots as options), not generic.
1. Resolve the question budget `B` from `--depth` (low=3, medium=6, high=10; default `medium`).
   Treat `B` as a **target for thoroughness, not a cap to dodge.** Keep asking until you
   genuinely understand the run, then stop — don't stop at the first three answers.
2. Interview the user **one `AskUserQuestion` at a time**, multiple-choice with concrete
   repo-grounded options, and **branch on answers** (a "known slow path" answer → next ask
   *which* path; a subsystem answer → ask *which* entrypoint/function). Cover, until each is
   concrete, at minimum:
   - **focus_areas** — the kind(s) of improvement (tests / performance / types / cleanup / …).
   - **surface** — which subsystem(s) / dirs are in scope; name them from the layout.
   - **motivation** — a specific known pain/hotspot, or audit-driven discovery? If specific,
     pin down exactly where and why.
   - **success & proof** — how a change earns its keep. The TDD gate is **pytest correctness,
     not speed**; if the user wants *measured* wins, the run must add benchmarks — surface that
     constraint and confirm the proof bar (behavior-identical refactor vs measured benchmark).
   - **guardrails** — invariants/off-limits (public API, schemas, DB/query semantics, deps).
   - **mode** — `fixed-N` (then `iterations`) vs `until-converged` (+ `max_iterations` /
     `budget_cap`); and **value_threshold** (how aggressive; default `0.5`).
3. Leave every other `run.json` field at its `cih.config.RunConfig` default (retries, team
   count, cooldown, `tdd_adapter`, `convergence_dry_streak`, …). Do NOT ask about them.
4. **Synthesize the answers into the run config:**
   - `focus_areas` — the kinds of improvement (short tags).
   - `brief` — a tight prose paragraph capturing **surface, motivation/hotspot, the success &
     proof bar, and guardrails**, in the user's own terms. This is the high-signal steer the
     high-planner audit treats as binding — do not drop the detail you gathered.
5. Present a summary that includes the **inferred inputs** (target_repo, Superset project,
   state_dir), the **brief**, and the **scoped run** (focus_areas, mode + caps, value_threshold),
   and ask a **single** "go ahead?" confirmation. If the user declines, let them adjust (any
   answer or inferred input), then re-summarize. On "yes", proceed to **Hand-off**.

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
     --value-threshold <x> [--focus <a> --focus <b> …] --brief "<synthesized brief>" \
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
5. **Add a watcher terminal so the run is observable.** The `--command` runs the loop headless in
   a detached "Command" terminal that shows no live output. Add a second terminal IN the new
   workspace that tails the progress the runner now emits to `<state_dir>/progress.md` (iteration
   start, "high-planner audit started", "audit done: X opps Y charters", per-team PASSED/FAILED,
   merged/rejected, and `run done`/`run FAILED` on exit):
   ```
   superset terminals create --workspace <new_workspace_id> \
     --command "touch <state_dir>/progress.md; tail -F <state_dir>/progress.md <state_dir>/run.json"
   ```
6. **Open and report.** `superset workspaces open <new_workspace_id>` to surface it (both the
   Command terminal and the watcher), then report the workspace id / deep link to the user and STOP.

> **Run in the current workspace instead (no new workspace).** If the user explicitly wants to watch
> the run in *this* workspace rather than spawn a fresh one, skip the `workspaces create` hand-off and
> run the loop here with `superset terminals create --workspace "$SUPERSET_WORKSPACE_ID" --command
> "$CIH --from-run-json <state_dir>/run.json --target-repo <clean_checkout>" --cwd <clean_checkout>`.
> The target MUST be a clean checkout (the runner's clean-tree preflight rejects a dirty tree — the
> current workspace's worktree is usually dirty, so point `--target-repo` at a clean one).

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
