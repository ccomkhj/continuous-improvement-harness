# CIH Interactive Q&A Scoping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a skill-only interactive Q&A scoping phase to CIH that, governed by a `--depth low|medium|high` budget (3/6/10 questions), interviews the user for the `run.json` intent params, then runs the existing autonomous loop.

**Architecture:** A shared `depth_budget()` helper in `cih/config.py` maps `--depth` to a question cap (and is unit-tested). The interview itself is orchestrator behavior described in prose in `.claude/skills/cih/SKILL.md`: ask one `AskUserQuestion` at a time over intent params (`focus_areas`, `mode`+caps, `value_threshold`), stop early when confident, assemble `run.json` via the unchanged `RunConfig.create()`, show a summary, take one confirmation, then enter the existing loop. The headless runner is untouched.

**Tech Stack:** Python 3.11+, pytest, existing `cih.config.RunConfig`, Claude Code skill (`AskUserQuestion`).

**Spec:** `docs/superpowers/specs/2026-06-07-cih-qa-scoping-design.md`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `cih/config.py` | Modify | Add `DEPTH_BUDGET` map + `depth_budget(name)` helper. No `RunConfig` change. |
| `tests/test_config.py` | Modify | Add tests for `depth_budget`. |
| `.claude/skills/cih/SKILL.md` | Modify | Add a "Scoping phase (interactive)" section: `--depth`, one-question interview, early-exit, summary + single confirm, skill-only note. |

No other files change. `cih/orchestrator.py`, `cih/runner.py`, agent contracts, and the `run.json` schema are untouched.

---

## Task 1: `depth_budget` helper in config

**Files:**
- Modify: `cih/config.py` (top-level, after `_MODES` on line 9)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
from cih.config import depth_budget, DEPTH_BUDGET, DEFAULT_DEPTH

def test_depth_budget_values():
    assert depth_budget("low") == 3
    assert depth_budget("medium") == 6
    assert depth_budget("high") == 10

def test_depth_budget_default():
    assert DEFAULT_DEPTH == "medium"
    assert depth_budget(None) == 6
    assert depth_budget(DEFAULT_DEPTH) == 6

def test_depth_budget_rejects_unknown():
    with pytest.raises(ConfigError):
        depth_budget("deep")

def test_depth_budget_map_exact():
    assert DEPTH_BUDGET == {"low": 3, "medium": 6, "high": 10}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -k depth -v`
Expected: FAIL — `ImportError: cannot import name 'depth_budget'`.

- [ ] **Step 3: Implement the helper**

In `cih/config.py`, immediately after the line `_MODES = {"fixed-N", "until-converged"}` (line 9), add:

```python
DEPTH_BUDGET = {"low": 3, "medium": 6, "high": 10}
DEFAULT_DEPTH = "medium"

def depth_budget(name: Optional[str] = None) -> int:
    """Map a --depth name to its question budget (upper bound). None → default."""
    if name is None:
        name = DEFAULT_DEPTH
    if name not in DEPTH_BUDGET:
        raise ConfigError(
            f"depth must be one of {sorted(DEPTH_BUDGET)} (got {name!r})"
        )
    return DEPTH_BUDGET[name]
```

(`Optional` is already imported on line 4; `ConfigError` is defined on line 6.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS — all existing config tests plus the four new `depth` tests.

- [ ] **Step 5: Commit**

```bash
git add cih/config.py tests/test_config.py
git commit -m "feat(cih): add depth_budget helper for Q&A scoping"
```

---

## Task 2: Document the scoping phase in SKILL.md

**Files:**
- Modify: `.claude/skills/cih/SKILL.md` (replace the `## Inputs` section, lines 10-12)
- Test: none (prose; verified by reading)

- [ ] **Step 1: Replace the `## Inputs` section**

In `.claude/skills/cih/SKILL.md`, replace these lines:

```markdown
## Inputs
- `target_repo` (absolute), `state_dir` (absolute, non-nested with target), `mode`
  (`fixed-N` with `iterations`, or `until-converged`), `focus_areas`.
```

with:

```markdown
## Inputs
- `target_repo` (absolute) and `state_dir` (absolute, non-nested with target) are **direct
  args** — never asked in the Q&A.
- `--depth low|medium|high` controls the scoping question budget: `low`=3, `medium`=6,
  `high`=10. Default `medium`. Resolve it with `cih.config.depth_budget(name)`, which raises
  `ConfigError` on an unknown value — surface that and stop before asking anything.

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
```

- [ ] **Step 2: Verify the edit reads correctly**

Run: `.venv/bin/python -c "import pathlib; t=pathlib.Path('.claude/skills/cih/SKILL.md').read_text(); assert '--depth low|medium|high' in t and 'Scoping phase' in t and 'fully autonomous' in t; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/cih/SKILL.md
git commit -m "docs(cih): document interactive Q&A scoping phase in skill"
```

---

## Task 3: Full suite green

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `.venv/bin/pytest -q`
Expected: all tests pass (existing modules unchanged, plus the four new `depth` tests).

- [ ] **Step 2: If anything fails**

Use superpowers:systematic-debugging before editing. Do not weaken or skip tests to go green.

---

## Self-Review notes

- **Spec coverage:** §3 depth arg → Task 1 (`depth_budget`, default, errors) + SKILL.md `--depth` doc. §4 intent params → SKILL.md step 2. §5 flow → SKILL.md steps 1-5. §6 validity (reuse `RunConfig.create`) → SKILL.md step 4. §7 surface → exactly Tasks 1-2. §8 testing → Task 1 tests + Task 3 suite. §9 non-goals (skill-only, no schema/artifact/role, `--depth` not persisted) → honored: no `RunConfig` field added, headless untouched.
- **Placeholder scan:** none — every code/doc step shows full content.
- **Type consistency:** `depth_budget`, `DEPTH_BUDGET`, `DEFAULT_DEPTH` used identically in Task 1 code and tests and referenced by name in SKILL.md.
