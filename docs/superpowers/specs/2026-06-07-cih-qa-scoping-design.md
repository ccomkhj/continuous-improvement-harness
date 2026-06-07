# CIH Interactive Q&A Scoping — Design Spec

**Date:** 2026-06-07
**Status:** Approved (brainstorming Q&A)
**Extends:** `docs/superpowers/specs/2026-06-05-cih-design.md`
**Branch:** `feat/cih-implementation`

## 1. Purpose

Add an interactive **Q&A scoping phase** to the CIH skill. Before the autonomous run
loop begins, the orchestrator interviews the user one question at a time until it is
confident it understands the goal, assembles a complete `run.json`, shows a summary for
a single confirmation, then runs **fully autonomously with no further interaction**.

The phase replaces "the user must hand-author a complete `run.json`" with a guided
interview for the *intent* parameters. It is a friendlier front door to the existing
`RunConfig` — not a new artifact, schema, or agent role.

## 2. Settled decisions (from brainstorming)

| Fork | Decision |
|------|----------|
| Q&A output | Fills the existing `run.json` intent params. No new artifact or schema. |
| Runtime | **Skill-only.** Headless `python -m cih.runner` is unchanged and still requires a complete `run.json`. |
| Unit & counting | One "session" = one question. The depth range is an **upper budget**; stop early once confident. |
| Depth map | `low` → 3, `medium` → 6, `high` → 10. Default `medium`. |
| Scope of questions | **Intent params only.** Tuning knobs keep `config.py` defaults. |
| Architecture | The Q&A runs **inside the orchestrator's skill-runtime pre-loop phase** (relaxes "no domain logic" for that pre-loop phase only; the loop and the entire headless orchestrator stay pure). |
| Confirm gate | Show assembled `run.json` summary → single "go ahead?" confirmation → fully autonomous. |

## 3. The `--depth` argument

- Values: `low` | `medium` | `high`.
- Question budget (upper bound): **`low`=3, `medium`=6, `high`=10.**
- Default when omitted: **`medium`**.
- Invalid value → error that lists the valid options and exits before any questions.
- The budget is a **cap with early exit**: the orchestrator asks at most that many
  questions and stops as soon as it has enough to populate every required intent param
  with confidence — it does not pad to the cap.

A `DEPTH_BUDGET` constant lives in `cih/config.py` (`{"low": 3, "medium": 6, "high": 10}`)
so the mapping is shared and unit-testable. `--depth` itself is a scoping-time control; it
is **not** persisted into `run.json`.

## 4. What the Q&A elicits (intent params only)

Questions are asked one at a time via `AskUserQuestion`, multiple-choice where possible.

**Elicited:**
- `focus_areas[]` — what to audit / improve in the target.
- `mode` — `fixed-N` (with `iterations`) vs `until-converged`, plus optional
  `max_iterations` / `budget_cap` bounds.
- `value_threshold` — how aggressive to be about which opportunities are worth doing.

**Direct skill args (never asked):** `target_repo` (absolute), `state_dir` (absolute,
non-nested).

**Left at defaults (never asked):** `convergence_dry_streak`, `plan_review_retries`,
`exec_review_retries`, `max_teams_per_iteration`, `integration_retries`,
`per_team_attempt_cap`, `cooldown_iterations`, `opportunity_max_attempts`, `tdd_adapter`.

The orchestrator chooses *which* of the elicited topics to ask, and in what order, to spend
its budget on what it does not yet know — e.g. if the user's invocation already implies a
mode, it spends questions on `focus_areas` and `value_threshold` instead.

## 5. Flow

```
skill invoked:  cih --target <abs> [--state-dir <abs>] [--depth medium]
  └─ orchestrator — SCOPING PHASE (skill only):
       parse + validate --depth → question budget B (default medium=6)
       loop, asking one AskUserQuestion at a time (multiple-choice where possible):
         - ask the highest-value unknown intent param
         - stop when all required intent params are confidently known, OR after B questions
       assemble run.json via RunConfig.create(target_repo, state_dir, mode, iterations,
                                               focus_areas, value_threshold, …defaults)
       present a summary of the assembled run.json (goal, focus_areas, mode, caps, threshold)
       ask a single "go ahead?" confirmation
         - no  → allow re-answer / adjust, then re-summarize
         - yes → proceed
  └─ orchestrator — AUTONOMOUS LOOP (unchanged from 2026-06-05 design):
       fully independent; no further questions until the run terminates.
```

## 6. Validity & error handling

- The assembled config goes through the **existing** `RunConfig.create()`, so all current
  invariants hold unchanged: `mode ∈ {fixed-N, until-converged}`; `fixed-N` requires a
  positive `iterations`; `until-converged` must not set `iterations`; `target_repo` and
  `state_dir` are absolute, distinct, non-nested, existing directories.
- If the Q&A somehow yields an invalid combination, `RunConfig.create()` raises
  `ConfigError`; the orchestrator surfaces it and re-asks the offending param rather than
  proceeding.
- Invalid `--depth` is caught **before** any question is asked.

## 7. Surface touched

| File | Change |
|------|--------|
| `.claude/skills/cih/SKILL.md` | New "Scoping phase (interactive)" section describing `--depth` parsing, the one-question-at-a-time interview over intent params, early-exit rule, the summary + single-confirm gate, and the handoff into the existing loop. Document that this phase is skill-only. |
| `cih/config.py` | Add `DEPTH_BUDGET = {"low": 3, "medium": 6, "high": 10}` and a small helper (e.g. `depth_budget(name) -> int`) that validates the name and returns the cap. No change to `RunConfig` fields or `create()`. |
| `tests/test_config.py` | Tests for `depth_budget`: each valid name → expected cap; default resolution; invalid name raises `ConfigError`. |

**Not touched:** `cih/orchestrator.py`, `cih/runner.py` (headless), any agent contract, the
`run.json` schema, the merge queue, the state protocol.

## 8. Testing

- **Unit (`tests/test_config.py`):** `depth_budget("low"|"medium"|"high")` returns
  `3|6|10`; unknown name raises `ConfigError`; the default ("medium") resolves to 6.
- **Doc conformance:** `SKILL.md` documents `--depth`, the default, the budgets, the
  early-exit rule, the summary + single-confirm gate, and the skill-only constraint.
- The interactive Q&A itself is orchestrator (skill-agent) behavior driven by `SKILL.md`
  prose; it is not unit-tested with a real LLM, consistent with the existing design's
  "no real-LLM calls in unit tests" non-goal.

## 9. Non-goals

- No Q&A in the headless runner (it requires a complete `run.json`, unchanged).
- No new `run.json` field, no new artifact, no new agent role.
- No questions about tuning knobs — they keep `config.py` defaults.
- `--depth` is not persisted; it only governs the scoping phase.
- No mid-run interaction: after the single confirmation, the run is fully autonomous.
