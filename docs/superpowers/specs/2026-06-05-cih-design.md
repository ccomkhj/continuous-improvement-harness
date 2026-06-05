# Continuous Improvement Harness (CIH) — Design Spec

**Date:** 2026-06-05
**Status:** Approved (pair-consult with codex, verdict: ship)
**Inspired by:** github.com/celesteanders/harness (generator+evaluator pattern)

## 1. Purpose

A hierarchical multi-agent harness that autonomously audits a **target codebase**, finds
high-value improvement opportunities, and applies them in **TDD-gated iterations**. It runs
both as an interactive Claude Code skill and as a headless Python runner, sharing one on-disk
JSON state format.

The harness operates on a target repository that is **always a separate parameter** from the
harness's own project directory. It never pushes and never stages files implicitly.

## 2. Settled decisions (do not relitigate)

| Fork | Decision |
|------|----------|
| Runtime | Hybrid: Claude Code skill **and** headless Python runner, shared JSON state |
| Domain | Self-improving codebase (audit → improve a target repo) |
| Iteration modes | Both `fixed-N` and `until-converged`, user picks per run |
| State | JSON files on disk under a `state_dir` |
| Team isolation | One git worktree per parallel team |
| Audit signals | User-provided focus areas + LLM code-read audit |
| Verification gate | TDD-enforced (mechanically verified) + execution-reviewer sign-off |
| v1 TDD adapter | **pytest-only**, with reviewer-only fallback for unsupported runners |

## 3. Agent hierarchy

| Agent | Count | Responsibility |
|-------|-------|----------------|
| **orchestrator** | 1 | Pure control flow + state I/O. Owns the run loop, spawns high-planner per iteration, runs the merge queue, detects convergence, owns all aggregate state. No domain logic. |
| **high-planner** | 1/iter | Audits the target (LLM code-read + user focus), updates the opportunity ledger, selects opportunities above threshold, groups independent ones into **team charters** (each with an impact manifest). Decides parallelism. |
| **planner** | 1/team | Charter → ordered task plan with **testable** acceptance criteria (`plan.json`). |
| **plan-reviewer** | 1/team | Skeptical approve/reject: scope, testability, TDD feasibility, conflict risk. Bounded re-plan loop. |
| **executor** | 1/team | Works in the team's git worktree. TDD: failing-test commit precedes impl commit, one logical commit per task. |
| **execution-reviewer** | 1/team | Separate skeptical QA: judges *on top of* a green mechanical `tdd_verifier` verdict — criteria met, no regressions, suspicious diffs. Bounded retry loop. |

## 4. Agent contracts (single source of truth)

Each role is a **versioned contract**, not just a prompt:

```
{
  role: "high-planner" | "planner" | ... ,
  agent_version: "<semver-or-hash>",   # recorded into every artifact it produces
  role_prompt: "<markdown body>",      # lives in .claude/agents/<role>.md
  input_schema: <JSON Schema>,
  output_schema: <JSON Schema>,
  allowed_tools: [...],
  runtime_adapter_settings: { ... }    # per-runtime knobs
}
```

- Both the **skill** and the **Python runner** render the agent from this contract and
  **validate every agent's output against `output_schema`** using the *same* validator code.
  Output that fails validation triggers a retry (identical mechanism in both runtimes).
- `agent_version` (or a prompt+schema hash) is written into each produced artifact so drift is
  detectable in state.
- **Conformance tests** with stub agents assert both runtimes produce schema-valid output for
  canned inputs, for every role.

## 5. Run loop & termination

### fixed-N
Run exactly N iterations (subject to the hard `max_iterations` / budget cap).

### until-converged
Stop when the **opportunity ledger** has no `open` opportunity above `value_threshold` AND no
retryable opportunity outside cooldown — i.e. a **dry iteration** is defined by *ledger state*,
not by planner prose. Stop after `convergence_dry_streak` (default 2) consecutive dry
iterations. A hard `max_iterations` and overall budget cap bound the loop unconditionally in
both modes.

### Opportunity ledger (`<state_dir>/ledger.json`, orchestrator-owned)
Each opportunity:
```
{ fingerprint,            # normalized title + target-scope hash (stable across iterations)
  scores: { value, confidence, effort, risk },
  rationale,              # required for both selected and rejected opportunities
  attempt_count,
  state }                 # open | in_progress | merged | rejected | deferred | cooldown | expired
```
Rejected/failed work enters `cooldown` for N iterations, then `expired` after a max attempt
count, so it cannot be re-proposed forever.

## 6. Per-iteration flow

```
orchestrator
  └─ high-planner: audit → update ledger → select → N team charters (+impact manifests)
       ├─ team-01 (own worktree, parallel) ┐
       │   planner → plan-reviewer(≤R)      │
       │   → executor (TDD) → tdd_verifier  │   teams run concurrently;
       │   → execution-reviewer(≤R)         │   each blocked only by its own gates
       ├─ team-02 ...                       ┤
       └─ team-NN ...                       ┘
  └─ orchestrator: MERGE QUEUE over PASSED teams (section 8)
  └─ orchestrator: record results, update ledger, decide continue/stop
```

## 7. TDD verification (`tdd_verifier`)

A deterministic, **no-LLM** verifier runs after the executor and **before** the
execution-reviewer. The reviewer judges on top of a *green* mechanical verdict — it is never the
only verifier.

### pytest adapter (v1)
Given the parent of the red commit, the red commit, and the green commit, the verifier asserts:
1. Parent of the red commit has a **clean tree** and the baseline suite passes.
2. The red commit touches **only declared test/spec paths**, and the declared test command
   **fails for the expected test identifiers** (a real assertion failure — not a collection or
   syntax error).
3. The green commit makes that same command **pass** and **does not modify any test path**.
4. The **full suite** passes.
5. No forbidden skip markers / deleted tests / test-count regressions were introduced.

It records the actual command, exit code, commit SHA, and output excerpts into `execution.json`
— sourced from the verifier, **never** from executor self-report.

### Limits & fallback (codex C3 rider)
- The "expected identifiers fail" proof requires a **test-runner adapter** (pytest in v1) or a
  planner-provided command + test-identifier contract the verifier can parse.
- If no adapter can *prove* the red failure, the task is **downgraded to reviewer-only TDD
  confidence** or marked **ineligible for autonomous TDD enforcement** (recorded in state).
- "No assertion weakening" is a **hard block only for obvious cases** (skips, deletions,
  test-count drops). Suspicious assertion *diffs* are **routed to the execution-reviewer**, not
  hard-failed by the verifier.

## 8. Integration: merge queue (not one-shot merge)

For each accepted team, in queue order:
1. Rebase/replay its branch onto the **current integration base**.
2. Run the **full verification suite** on the rebased branch.
3. Re-run the **execution-reviewer** against the rebased result.
4. Pass → fast-forward into the integration base. Fail → classify as `integration_retry` /
   `replan` / `reject` (distinct from a raw git conflict).

### Budget & bounds (codex C2 rider)
The merge queue must be explicitly bounded so a run cannot become
`O(teams × full-suite-cost × retries)`:
- Bounded **team count** per iteration.
- Bounded **integration-retry count**, **counted against the global attempt bounds** (section 9)
  — integration retries cannot escape the global cap.
- **Cheap prechecks from the impact manifest** (file/API/test overlap) to predict collisions and
  order the queue before paying for full re-verification.

### Impact manifest (per charter, machine-readable)
`{ intended_files, intended_apis, intended_tests, dependencies, parallelization_exclusions }`.
Used by the high-planner to reduce overlap up front and by the orchestrator to order/precheck
the merge queue.

## 9. Retry semantics: typed attempt records

Per-team **attempt record** with a typed transition table — "retry" is never one vague action:

| Class | Trigger | Action |
|-------|---------|--------|
| `plan_retry` | plan-reviewer reject | re-plan, same worktree, plan-reviewer feedback |
| `execution_retry` | exec-reviewer / test / verifier fail | re-execute from team base SHA, fresh/reset worktree, tests preserved unless re-plan says otherwise |
| `integration_retry` | merge-queue re-verify fail | re-execute against a **new integration base SHA** |
| `final_reject` | bound exceeded | discard worktree, log, return opportunity to ledger as `cooldown` |

Each attempt stores `base_sha`, `branch`, `worktree_path`, `parent_attempt_id`,
`feedback_input`, `artifacts`, `cleanup_policy`. Failed attempts are **preserved for audit**;
exactly one attempt is `current`. Plan-review failure ⇒ re-plan; execution/test/integration
failure ⇒ re-execute, escalating to re-plan after the bound. All retry counters (including
integration retries) share the **global per-team and per-run bounds**.

## 10. State protocol

`state_dir` layout:
```
<state_dir>/
  run.json                 # config + status (orchestrator-owned)
  ledger.json              # opportunity ledger (orchestrator-owned)
  progress.md              # cumulative human-readable log (orchestrator-owned)
  iterations/iter-NNN/
    audit.json             # high-planner findings (orchestrator-owned)
    teams.json             # charters + impact manifests (orchestrator-owned)
    iteration.md           # human summary (orchestrator-owned)
    teams/team-NN/
      plan.json            # team-owned
      plan_review.json     # team-owned
      execution.json       # team-owned (verifier-sourced fields)
      exec_review.json     # team-owned
      attempts/attempt-NN.json   # team-owned
```

**Header on every file:** `schema_version, run_id, iteration_id, team_id, attempt_id, status,
owner, created_at, updated_at`.

**Invariants:**
- **Atomic writes** — write temp file + `os.rename` (atomic on same filesystem).
- **Ownership** — a team writes only under its own `teams/team-NN/`; `run.json`, `ledger.json`,
  `audit.json`, `teams.json`, `iteration.md`, `progress.md` are **orchestrator-only**.
- **Monotonic transitions** — `status` is an enum with allowed transitions enforced by a
  **shared validator** used by both entry points (codex C1 rider).
- **resume()** — reconciles JSON against ground truth (do worktrees exist? branches? do commit
  SHAs in `execution.json` match git?) and repairs or aborts before continuing. JSON is never
  trusted alone.

## 11. Safety: enforced invariants (not policy)

- `target_repo` and `state_dir` are **absolute** paths, validated **distinct and non-nested** at
  startup. **`state_dir` lives OUTSIDE the target repo** (default: the harness project area), so
  agents working in target worktrees can never stage harness artifacts.
- **Preflight checks:** target base tree clean; reserved branch namespace `cih/<run_id>/team-NN`;
  remote push disabled/wrapped; forbidden path globs (`.harness/`, `.consult/`, harness source,
  secret patterns).
- **Explicit-file staging wrapper:** all staging goes through a wrapper that stages only paths
  declared in the plan/impact-manifest — **`git add -A` is structurally impossible**, not merely
  discouraged. Executor/reviewer phases **cannot bypass the wrapper with raw git** (codex C7
  rider).
- Every git command is **logged** to `progress.md` / per-team logs.
- Each agent invocation is passed **both absolute paths explicitly**; no reliance on inherited
  cwd.

## 12. Two entry points

- **Skill** (`.claude/skills/cih/SKILL.md`): interactive; orchestrator spawns agents via the
  Agent/Task tools; real git worktrees.
- **Python runner** (`.harness/runner.py` + `orchestrator.py`): headless; renders agents from
  the same contracts, drives them via `claude -p --append-system-prompt`, reads/writes the
  identical JSON schema, manages worktrees in Python.

Both share: the agent contracts (section 4), the output-schema validator, the state header +
transition validator (section 10), the staging wrapper (section 11).

## 13. Parameters (`run.json`)

`mode` (`fixed-N` | `until-converged`), `iterations` / `max_iterations`, `budget_cap`,
`target_repo` (abs), `state_dir` (abs), `focus_areas[]`, `value_threshold`,
`convergence_dry_streak` (2), `plan_review_retries` (2), `exec_review_retries` (2),
`max_teams_per_iteration`, `integration_retries`, `per_team_attempt_cap`,
`cooldown_iterations`, `opportunity_max_attempts`, `tdd_adapter` (`pytest`).

## 14. Testing the harness itself

- **Unit (pytest, stub agents — no real LLM):** orchestrator loop control, both termination
  modes, ledger state machine + dry-iteration definition, merge-queue ordering + bounds, attempt
  transition table, state header + transition validator, atomic write + `resume()` reconciliation
  round-trips, the staging wrapper (proves `git add -A` is unreachable), the pytest
  `tdd_verifier` (red/green/clean-tree/test-touch/full-suite/weakening cases).
- **Conformance:** each agent role, both runtimes, schema-valid output for canned inputs.
- **Integration smoke:** one end-to-end run against a tiny throwaway git repo.

## 15. Non-goals (v1)

- No auto-push, no PR creation (user integrates).
- No cross-team live coordination (independence is by construction via charters + impact
  manifests).
- No real-LLM calls in unit tests.
- No test-runner adapters beyond pytest (others use the reviewer-only fallback).

## 16. Review provenance

Hardened via a 5-round pair-consult with codex (`.consult/`). Codex verdict: **ship**. The seven
gaps (state protocol, semantic-merge, mechanical TDD proof, convergence-on-noise, runtime SSoT,
retry semantics, enforced safety) and the two R4 riders (merge-queue budgeting; TDD-via-adapters
+ reviewer fallback) are all incorporated above.
