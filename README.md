# Continuous Improvement Harness (CIH)

Hierarchical multi-agent harness that autonomously audits a target codebase, finds high-value
improvements, and applies them in TDD-gated iterations.

Each iteration a **high-planner** audits the target and emits non-overlapping team charters.
Every charter runs in its own isolated git worktree where a **planner** / **plan-reviewer** /
**executor** / **execution-reviewer** team produces red-green TDD commits, gated by a mechanical
pytest verifier. Passing teams are integrated through a bounded merge queue that re-runs the full
suite before advancing the integration head. The opportunity ledger drives convergence.

## Run (headless)
```bash
python -m cih.runner --mode fixed-N --iterations 3 \
  --target-repo /abs/path/to/target --state-dir /abs/path/to/state \
  --focus tests --focus performance
```

`until-converged` runs until the ledger is dry (no open opportunity above the value threshold
for `convergence_dry_streak` iterations), bounded by `--max-iterations`:
```bash
python -m cih.runner --mode until-converged \
  --target-repo /abs/path/to/target --state-dir /abs/path/to/state \
  --max-iterations 25
```

## Run (interactive)
Invoke the `cih` skill in Claude Code (`.claude/skills/cih/SKILL.md`) with the same parameters.
The skill renders the same agent contracts and orchestration steps, delegating to the Agent/Task
tools instead of `claude -p`.

## Safety
- The harness **never pushes** and **never uses `git add -A`** — staging is explicit-only.
- `state_dir` is always absolute and lives **outside** the target repo (non-nested).
- All work happens in disposable per-team worktrees; the target's working tree is never dirtied.

See `docs/superpowers/specs/2026-06-05-cih-design.md` for the full design.

## Tests
```bash
python -m pytest -q
```
