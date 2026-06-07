# Continuous Improvement Harness (CIH)

> A multi-agent system that **audits any codebase, finds high-value improvements, and ships them
> in TDD-gated iterations** — autonomously, and unable to push or bulk-stage by construction.

<p>
  <a href="https://pypi.org/project/cih-agent/"><img alt="PyPI" src="https://img.shields.io/pypi/v/cih-agent.svg"></a>
  <a href="https://github.com/ccomkhj/continuous-improvement-harness/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/ccomkhj/continuous-improvement-harness/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/pypi/pyversions/cih-agent.svg">
  <img alt="TDD-gated" src="https://img.shields.io/badge/merges-TDD--gated-success.svg">
  <img alt="No-push by construction" src="https://img.shields.io/badge/safety-no--push-critical.svg">
</p>

A change only merges if a **non-LLM verifier proves** — by checking out the commits and running
the tests itself — that a new test failed before the fix and passes after, with the full suite
still green. Every team works in a disposable git worktree; `git push` and `git add -A` are
blocked at the wrapper level. Runs as a headless CLI or an interactive Claude Code skill.

## How it works

```mermaid
flowchart TB
    ORCH["orchestrator · pure control flow"] --> HP["high-planner<br/>audit → ledger → charters"]
    subgraph teams["parallel teams · one worktree each"]
        T1["planner → plan-reviewer →<br/>executor → tdd_verifier (pytest) →<br/>execution-reviewer"]
        T2["team-NN …"]
    end
    HP --> T1 & T2
    T1 & T2 --> MQ["merge queue<br/>rebase → re-verify → fast-forward"]
    MQ --> DEC{"ledger dry / N reached?"}
    DEC -->|no| ORCH
    DEC -->|yes| DONE["stop · report.html"]
```

A **high-planner** scores improvement opportunities and splits them into non-overlapping charters.
Each charter runs a five-agent pipeline in its own worktree, gated by a mechanical pytest verifier
and a skeptical reviewer. Passing teams merge **one at a time** through a queue that re-runs the
full suite before fast-forwarding. An **opportunity ledger** remembers what's been tried, cools
down failures, and drives the run to convergence.

## Quick start

Requires Python 3.11+ and the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code)
(`claude`) on your `PATH` — CIH drives it for the agent pipeline.

```bash
pip install cih-agent

# exactly 3 iterations, focused on tests + performance
cih --mode fixed-N --iterations 3 \
  --target-repo /abs/path/to/target --state-dir /abs/path/to/state \
  --focus tests --focus performance

# or run until converged (bounded by --max-iterations)
cih --mode until-converged \
  --target-repo /abs/path/to/target --state-dir /abs/path/to/state
```

`pip install cih-agent` installs the `cih` console command (the import name stays `cih`);
`cih …` is equivalent to `python -m cih.runner …`.

`target-repo` and `state-dir` must be absolute, distinct, and non-nested. Add `--report` to write
a self-contained `report.html` after every iteration.

## Use it in another repo

**Headless** — no setup beyond the install. From anywhere, point `--target-repo` at the repo
you want to improve and keep `--state-dir` *outside* it:

```bash
pip install cih-agent
cih --mode fixed-N --iterations 3 \
  --target-repo /abs/path/to/your-repo \
  --state-dir   /abs/path/to/your-repo-cih-state   # outside the target repo
```

**Interactive (`/cih` skill).** The skill and its agents aren't auto-installed by pip (Claude
Code loads them from `.claude/`, not from site-packages). Install them once, then invoke `/cih`
inside a Claude Code session:

```bash
cih install-skill                       # installs into ~/.claude (available in every repo)
cih install-skill --dest /path/to/your-repo/.claude   # or scope to one repo
```

The interactive skill runs a short scoping interview, then runs autonomously.

## Why it's safe to leave running

- **Improvements are proven, not asserted** — the TDD verifier independently confirms red→green
  with the full suite passing; it hard-blocks skip markers and flags weak assertions.
- **Can't push or bulk-stage** — `git push`, `git remote`, and `git add -A/--all/.` are
  structurally unreachable; forbidden paths (`secrets/`, `*.pem`, `*.key`) are rejected.
- **Never touches your tree** — all work happens in disposable worktrees; state lives outside the
  target repo and every git command is logged.

## Tests

```bash
python -m pytest -q
```

> Full config lives in `RunConfig` (`cih/config.py`); role prompts in `.claude/agents/`.
</content>
