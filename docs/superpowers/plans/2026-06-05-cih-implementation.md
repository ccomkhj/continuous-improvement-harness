# Continuous Improvement Harness (CIH) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hierarchical multi-agent harness that autonomously audits a target codebase, finds high-value improvements, and applies them in TDD-gated iterations — runnable as both a headless Python runner and a Claude Code skill, sharing one on-disk JSON state format.

**Architecture:** A pure-control-flow `orchestrator` runs a loop (fixed-N or until-converged) that spawns a `high-planner` to audit and decompose work into parallel teams (planner → plan-reviewer → executor → execution-reviewer), each isolated in a git worktree. Accepted teams are integrated through a bounded merge queue with re-verification. All state is atomic, owned, versioned JSON on disk; all agents are versioned contracts validated against output schemas by shared code. Built bottom-up: every component is tested with stub agents (no real LLM) before orchestration wires them together.

**Tech Stack:** Python 3.11+, pytest, `jsonschema`, GitPython-free (subprocess `git`), `dataclasses`, Claude Code (skill + `claude -p` headless adapter).

---

## File Structure

Source package `cih/` (importable; the headless CLI is `python -m cih.runner`):

| File | Responsibility |
|------|----------------|
| `cih/__init__.py` | Package marker, version |
| `cih/state.py` | State-file header dataclass, atomic write (temp+rename), read |
| `cih/transitions.py` | Status enum + allowed-transition validator (shared) |
| `cih/config.py` | `run.json` load/validate, absolute + non-nested path safety |
| `cih/ledger.py` | Opportunity ledger: fingerprint, states, dry-iteration logic, cooldown/expiry |
| `cih/safety.py` | Path validation, forbidden globs, preflight checks, git-command logging |
| `cih/staging.py` | Explicit-file staging wrapper (makes `git add -A` unreachable) |
| `cih/worktree.py` | Git worktree manager: create/remove, branch namespace, base SHA |
| `cih/tdd_verifier.py` | pytest adapter: red/green/clean-tree/full-suite/weakening checks |
| `cih/attempts.py` | Typed attempt records + transition table |
| `cih/contracts.py` | Agent contract dataclass + output-schema validation (shared) |
| `cih/agents.py` | Agent invocation adapter (stubbable; real = `claude -p`) |
| `cih/team.py` | Per-team pipeline (planner→review→exec→verify→review) with bounded retries |
| `cih/merge_queue.py` | Bounded integration merge queue with re-verification |
| `cih/orchestrator.py` | Run loop, termination, resume() reconciliation |
| `cih/runner.py` | Headless CLI entry point |
| `.claude/agents/*.md` | Six role prompt bodies (rendered from contracts) |
| `.claude/skills/cih/SKILL.md` | Interactive skill orchestration doc |
| `tests/test_*.py` | One test module per source module + conformance + integration smoke |

> **Note on naming:** the spec illustrated the headless entry as `.harness/runner.py`; we use an importable package `cih/` with CLI `python -m cih.runner` instead (cleaner imports, testability). `state_dir` on disk still defaults to `.cih/` and is always outside the target repo.

---

## Task 1: Project scaffold

**Files:**
- Create: `cih/__init__.py`
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Test: `tests/test_scaffold.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scaffold.py
import cih

def test_package_exposes_version():
    assert isinstance(cih.__version__, str)
    assert cih.__version__.count(".") >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scaffold.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih'`

- [ ] **Step 3: Create the package and config**

```toml
# pyproject.toml
[project]
name = "cih"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["jsonschema>=4.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```python
# cih/__init__.py
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e ".[dev]" && python -m pytest tests/test_scaffold.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cih/__init__.py pyproject.toml tests/__init__.py tests/test_scaffold.py
git commit -m "feat: project scaffold for cih package"
```

---

## Task 2: State file header + atomic read/write

**Files:**
- Create: `cih/state.py`
- Test: `tests/test_state.py`

State files all carry a header and are written atomically (temp file + `os.rename`, atomic on the same filesystem).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
import json
from pathlib import Path
from cih.state import StateHeader, write_state, read_state, SCHEMA_VERSION

def _header():
    return StateHeader(
        run_id="run-1", iteration_id="iter-001", team_id=None,
        attempt_id=None, status="open", owner="orchestrator",
    )

def test_write_then_read_roundtrips_with_header(tmp_path):
    path = tmp_path / "run.json"
    write_state(path, _header(), {"mode": "fixed-N"})
    doc = read_state(path)
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["run_id"] == "run-1"
    assert doc["status"] == "open"
    assert doc["owner"] == "orchestrator"
    assert doc["body"] == {"mode": "fixed-N"}
    assert "created_at" in doc and "updated_at" in doc

def test_write_is_atomic_no_temp_left_behind(tmp_path):
    path = tmp_path / "run.json"
    write_state(path, _header(), {"x": 1})
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "run.json"]
    assert leftovers == []

def test_rewrite_preserves_created_at_bumps_updated_at(tmp_path):
    path = tmp_path / "run.json"
    write_state(path, _header(), {"v": 1})
    first = read_state(path)
    write_state(path, _header(), {"v": 2})
    second = read_state(path)
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]
    assert second["body"] == {"v": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.state'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/state.py
import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

SCHEMA_VERSION = 1

@dataclass
class StateHeader:
    run_id: str
    iteration_id: Optional[str]
    team_id: Optional[str]
    attempt_id: Optional[str]
    status: str
    owner: str

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def write_state(path: Path, header: StateHeader, body: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    created_at = _now()
    if path.exists():
        try:
            created_at = json.loads(path.read_text())["created_at"]
        except (json.JSONDecodeError, KeyError):
            pass
    doc = {"schema_version": SCHEMA_VERSION, **asdict(header),
           "created_at": created_at, "updated_at": _now(), "body": body}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)  # atomic on same filesystem
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def read_state(path: Path) -> dict:
    return json.loads(Path(path).read_text())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_state.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/state.py tests/test_state.py
git commit -m "feat: atomic versioned state read/write"
```

---

## Task 3: Status transition validator

**Files:**
- Create: `cih/transitions.py`
- Test: `tests/test_transitions.py`

Shared by both entry points so the skill and runner enforce identical state machines.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transitions.py
import pytest
from cih.transitions import Status, is_valid_transition, assert_transition, InvalidTransition

def test_open_can_go_in_progress():
    assert is_valid_transition(Status.OPEN, Status.IN_PROGRESS)

def test_merged_is_terminal():
    assert not is_valid_transition(Status.MERGED, Status.OPEN)
    assert not is_valid_transition(Status.MERGED, Status.IN_PROGRESS)

def test_cannot_skip_from_open_to_merged():
    assert not is_valid_transition(Status.OPEN, Status.MERGED)

def test_assert_transition_raises_on_invalid():
    with pytest.raises(InvalidTransition):
        assert_transition(Status.MERGED, Status.OPEN)

def test_assert_transition_passes_on_valid():
    assert_transition(Status.IN_PROGRESS, Status.MERGED)  # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transitions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.transitions'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/transitions.py
from enum import Enum

class Status(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    MERGED = "merged"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    COOLDOWN = "cooldown"
    EXPIRED = "expired"

class InvalidTransition(Exception):
    pass

# monotonic-ish: terminal states cannot leave; cooldown can re-open
_ALLOWED = {
    Status.OPEN: {Status.IN_PROGRESS, Status.DEFERRED, Status.REJECTED},
    Status.IN_PROGRESS: {Status.MERGED, Status.REJECTED, Status.COOLDOWN},
    Status.COOLDOWN: {Status.OPEN, Status.EXPIRED},
    Status.DEFERRED: {Status.OPEN, Status.EXPIRED},
    Status.REJECTED: {Status.COOLDOWN, Status.EXPIRED},
    Status.MERGED: set(),
    Status.EXPIRED: set(),
}

def is_valid_transition(src: Status, dst: Status) -> bool:
    return dst in _ALLOWED.get(src, set())

def assert_transition(src: Status, dst: Status) -> None:
    if not is_valid_transition(src, dst):
        raise InvalidTransition(f"{src.value} -> {dst.value} is not allowed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_transitions.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/transitions.py tests/test_transitions.py
git commit -m "feat: shared status transition validator"
```

---

## Task 4: Run config + path safety

**Files:**
- Create: `cih/config.py`
- Test: `tests/test_config.py`

`target_repo` and `state_dir` must be absolute, distinct, and non-nested; `state_dir` must be outside `target_repo`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from cih.config import RunConfig, ConfigError

def test_valid_config(tmp_path):
    target = tmp_path / "target"; state = tmp_path / "state"
    target.mkdir(); state.mkdir()
    cfg = RunConfig.create(mode="fixed-N", iterations=3,
                           target_repo=str(target), state_dir=str(state))
    assert cfg.mode == "fixed-N"
    assert cfg.iterations == 3
    assert cfg.plan_review_retries == 2  # default
    assert cfg.tdd_adapter == "pytest"

def test_rejects_relative_paths(tmp_path):
    with pytest.raises(ConfigError):
        RunConfig.create(mode="fixed-N", iterations=1,
                         target_repo="relative/target", state_dir=str(tmp_path))

def test_rejects_state_dir_nested_in_target(tmp_path):
    target = tmp_path / "target"; target.mkdir()
    nested = target / "state"; nested.mkdir()
    with pytest.raises(ConfigError):
        RunConfig.create(mode="fixed-N", iterations=1,
                         target_repo=str(target), state_dir=str(nested))

def test_rejects_unknown_mode(tmp_path):
    target = tmp_path / "t"; state = tmp_path / "s"; target.mkdir(); state.mkdir()
    with pytest.raises(ConfigError):
        RunConfig.create(mode="bogus", iterations=1,
                         target_repo=str(target), state_dir=str(state))

def test_roundtrip_to_dict(tmp_path):
    target = tmp_path / "t"; state = tmp_path / "s"; target.mkdir(); state.mkdir()
    cfg = RunConfig.create(mode="until-converged", target_repo=str(target),
                           state_dir=str(state), focus_areas=["tests"])
    d = cfg.to_dict()
    assert d["focus_areas"] == ["tests"]
    assert RunConfig.from_dict(d).focus_areas == ["tests"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/config.py
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

class ConfigError(Exception):
    pass

_MODES = {"fixed-N", "until-converged"}

@dataclass
class RunConfig:
    mode: str
    target_repo: str
    state_dir: str
    iterations: Optional[int] = None
    max_iterations: int = 25
    budget_cap: Optional[int] = None
    focus_areas: list = field(default_factory=list)
    value_threshold: float = 0.5
    convergence_dry_streak: int = 2
    plan_review_retries: int = 2
    exec_review_retries: int = 2
    max_teams_per_iteration: int = 4
    integration_retries: int = 2
    per_team_attempt_cap: int = 4
    cooldown_iterations: int = 2
    opportunity_max_attempts: int = 3
    tdd_adapter: str = "pytest"

    @staticmethod
    def _validate_paths(target_repo: str, state_dir: str) -> None:
        for label, p in (("target_repo", target_repo), ("state_dir", state_dir)):
            if not os.path.isabs(p):
                raise ConfigError(f"{label} must be an absolute path: {p}")
        t = Path(target_repo).resolve()
        s = Path(state_dir).resolve()
        if t == s:
            raise ConfigError("target_repo and state_dir must be distinct")
        if t in s.parents or s in t.parents:
            raise ConfigError("state_dir must not be nested inside target_repo (or vice versa)")

    @classmethod
    def create(cls, **kwargs) -> "RunConfig":
        if kwargs.get("mode") not in _MODES:
            raise ConfigError(f"mode must be one of {_MODES}")
        cls._validate_paths(kwargs["target_repo"], kwargs["state_dir"])
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunConfig":
        return cls.create(**d)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/config.py tests/test_config.py
git commit -m "feat: run config with enforced path safety"
```

---

## Task 5: Opportunity ledger

**Files:**
- Create: `cih/ledger.py`
- Test: `tests/test_ledger.py`

The ledger defines what "dry" means (state-based, not planner prose), and decays rejected work via cooldown→expired.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ledger.py
from cih.ledger import Ledger, Opportunity, fingerprint

def test_fingerprint_is_stable_and_normalized():
    a = fingerprint("Improve  Test Coverage", "src/foo.py")
    b = fingerprint("improve test coverage", "src/foo.py")
    assert a == b

def test_add_and_select_above_threshold():
    led = Ledger()
    led.upsert(Opportunity(fp=fingerprint("a", "x"), title="a", scope="x",
                           value=0.9, confidence=0.8, effort=0.2, risk=0.1,
                           rationale="high value"))
    led.upsert(Opportunity(fp=fingerprint("b", "y"), title="b", scope="y",
                           value=0.2, confidence=0.5, effort=0.5, risk=0.5,
                           rationale="low value"))
    selected = led.select_open(value_threshold=0.5)
    assert [o.title for o in selected] == ["a"]

def test_dry_when_no_open_above_threshold_and_none_retryable():
    led = Ledger()
    led.upsert(Opportunity(fp="f1", title="t", scope="s", value=0.1,
                           confidence=0.1, effort=0.1, risk=0.1, rationale="r"))
    assert led.is_dry(value_threshold=0.5, current_iteration=5)

def test_cooldown_blocks_reselection_until_expired(monkeypatch):
    led = Ledger()
    o = Opportunity(fp="f", title="t", scope="s", value=0.9, confidence=0.9,
                    effort=0.1, risk=0.1, rationale="r")
    led.upsert(o)
    led.mark_cooldown("f", current_iteration=1, cooldown_iterations=2)
    # within cooldown -> not selectable, not dry-blocking-clear
    assert led.select_open(value_threshold=0.5, current_iteration=2) == []
    # after cooldown -> reopened and selectable
    assert [x.title for x in led.select_open(value_threshold=0.5, current_iteration=3)] == ["t"]

def test_expires_after_max_attempts():
    led = Ledger()
    o = Opportunity(fp="f", title="t", scope="s", value=0.9, confidence=0.9,
                    effort=0.1, risk=0.1, rationale="r")
    led.upsert(o)
    for i in range(3):
        led.record_attempt_failure("f", current_iteration=i,
                                    cooldown_iterations=0, max_attempts=3)
    assert led.get("f").state == "expired"
    assert led.select_open(value_threshold=0.5, current_iteration=99) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.ledger'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/ledger.py
import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

def fingerprint(title: str, scope: str) -> str:
    norm = re.sub(r"\s+", " ", title.strip().lower())
    return hashlib.sha256(f"{norm}|{scope}".encode()).hexdigest()[:16]

@dataclass
class Opportunity:
    fp: str
    title: str
    scope: str
    value: float
    confidence: float
    effort: float
    risk: float
    rationale: str
    state: str = "open"
    attempt_count: int = 0
    cooldown_until: Optional[int] = None

class Ledger:
    def __init__(self):
        self._items: dict[str, Opportunity] = {}

    def upsert(self, opp: Opportunity) -> None:
        existing = self._items.get(opp.fp)
        if existing and existing.state in ("merged", "expired"):
            return  # terminal; ignore re-discovery
        if existing:
            opp.attempt_count = existing.attempt_count
            opp.state = existing.state
            opp.cooldown_until = existing.cooldown_until
        self._items[opp.fp] = opp

    def get(self, fp: str) -> Optional[Opportunity]:
        return self._items.get(fp)

    def _refresh_cooldowns(self, current_iteration: Optional[int]) -> None:
        if current_iteration is None:
            return
        for o in self._items.values():
            if o.state == "cooldown" and o.cooldown_until is not None \
                    and current_iteration >= o.cooldown_until:
                o.state = "open"
                o.cooldown_until = None

    def select_open(self, value_threshold: float,
                    current_iteration: Optional[int] = None) -> list[Opportunity]:
        self._refresh_cooldowns(current_iteration)
        return [o for o in self._items.values()
                if o.state == "open" and o.value >= value_threshold]

    def is_dry(self, value_threshold: float, current_iteration: int) -> bool:
        self._refresh_cooldowns(current_iteration)
        actionable = self.select_open(value_threshold, current_iteration)
        retryable = [o for o in self._items.values() if o.state == "cooldown"]
        return not actionable and not retryable

    def mark_merged(self, fp: str) -> None:
        self._items[fp].state = "merged"

    def mark_cooldown(self, fp: str, current_iteration: int,
                      cooldown_iterations: int) -> None:
        o = self._items[fp]
        o.state = "cooldown"
        o.cooldown_until = current_iteration + cooldown_iterations

    def record_attempt_failure(self, fp: str, current_iteration: int,
                               cooldown_iterations: int, max_attempts: int) -> None:
        o = self._items[fp]
        o.attempt_count += 1
        if o.attempt_count >= max_attempts:
            o.state = "expired"
            o.cooldown_until = None
        else:
            self.mark_cooldown(fp, current_iteration, cooldown_iterations)

    def to_dict(self) -> dict:
        return {fp: asdict(o) for fp, o in self._items.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "Ledger":
        led = cls()
        for fp, raw in d.items():
            led._items[fp] = Opportunity(**raw)
        return led
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/ledger.py tests/test_ledger.py
git commit -m "feat: opportunity ledger with cooldown/expiry and dry detection"
```

---

## Task 6: Git command runner + logging

**Files:**
- Create: `cih/safety.py`
- Test: `tests/test_safety.py`

A single logged git entry point. Every git call goes through `run_git`, which appends to a log.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_safety.py
import subprocess
import pytest
from pathlib import Path
from cih.safety import run_git, GitError, forbidden_paths, validate_no_forbidden

def _init_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)

def test_run_git_logs_command(tmp_path):
    _init_repo(tmp_path)
    log = []
    out = run_git(["rev-parse", "--is-inside-work-tree"], cwd=tmp_path, log=log.append)
    assert out.strip() == "true"
    assert any("rev-parse" in line for line in log)

def test_run_git_raises_on_failure(tmp_path):
    _init_repo(tmp_path)
    with pytest.raises(GitError):
        run_git(["checkout", "does-not-exist"], cwd=tmp_path)

def test_validate_no_forbidden_blocks_harness_paths():
    bad = ["src/app.py", ".cih/run.json"]
    with pytest.raises(GitError):
        validate_no_forbidden(bad, forbidden_paths())

def test_validate_no_forbidden_allows_clean_paths():
    validate_no_forbidden(["src/app.py", "tests/test_app.py"], forbidden_paths())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_safety.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.safety'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/safety.py
import fnmatch
import subprocess
from pathlib import Path
from typing import Callable, Optional

class GitError(Exception):
    pass

_FORBIDDEN = [".cih/*", ".cih", ".harness/*", ".consult/*",
              "**/.cih/*", "*.pem", "*.key", "**/secrets/*"]

def forbidden_paths() -> list[str]:
    return list(_FORBIDDEN)

def validate_no_forbidden(paths: list[str], patterns: list[str]) -> None:
    for p in paths:
        for pat in patterns:
            if fnmatch.fnmatch(p, pat) or p == pat.rstrip("/*"):
                raise GitError(f"path '{p}' matches forbidden pattern '{pat}'")

def run_git(args: list[str], cwd: Path,
            log: Optional[Callable[[str], None]] = None) -> str:
    cmd = ["git", *args]
    if log:
        log(f"git -C {cwd} {' '.join(args)}")
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_safety.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/safety.py tests/test_safety.py
git commit -m "feat: logged git runner and forbidden-path validation"
```

---

## Task 7: Explicit-file staging wrapper

**Files:**
- Create: `cih/staging.py`
- Test: `tests/test_staging.py`

Stages only explicitly-declared paths. `git add -A`/`.`/`*` are structurally rejected.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_staging.py
import subprocess
import pytest
from pathlib import Path
from cih.staging import stage_files, StagingError

def _init_repo(path: Path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)

def test_stages_only_declared_files(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    stage_files(tmp_path, ["a.py"])
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                            cwd=tmp_path, capture_output=True, text=True).stdout.split()
    assert staged == ["a.py"]

def test_rejects_add_all_tokens(tmp_path):
    _init_repo(tmp_path)
    for token in ("-A", ".", "*", ":/", "--all"):
        with pytest.raises(StagingError):
            stage_files(tmp_path, [token])

def test_rejects_forbidden_path(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / ".cih").mkdir()
    (tmp_path / ".cih" / "run.json").write_text("{}")
    with pytest.raises(StagingError):
        stage_files(tmp_path, [".cih/run.json"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_staging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.staging'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/staging.py
from pathlib import Path
from typing import Callable, Optional
from cih.safety import run_git, forbidden_paths, validate_no_forbidden, GitError

class StagingError(Exception):
    pass

_BANNED_TOKENS = {"-A", "--all", ".", "*", ":/", ":", "-u", "--update"}

def stage_files(repo: Path, paths: list[str],
                log: Optional[Callable[[str], None]] = None) -> None:
    if not paths:
        raise StagingError("no paths declared; explicit staging requires at least one file")
    for p in paths:
        if p.strip() in _BANNED_TOKENS or p.strip().startswith("-"):
            raise StagingError(f"refusing wildcard/all-style token: {p!r}")
    try:
        validate_no_forbidden(paths, forbidden_paths())
    except GitError as e:
        raise StagingError(str(e)) from e
    # '--' terminator: everything after is a literal pathspec, never a flag
    run_git(["add", "--", *paths], cwd=repo, log=log)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_staging.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/staging.py tests/test_staging.py
git commit -m "feat: explicit-file staging wrapper (git add -A unreachable)"
```

---

## Task 8: Git worktree manager

**Files:**
- Create: `cih/worktree.py`
- Test: `tests/test_worktree.py`

Creates/removes worktrees on reserved branch namespace `cih/<run_id>/team-NN`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worktree.py
import subprocess
import pytest
from pathlib import Path
from cih.worktree import WorktreeManager

def _seed_repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("hi")
    subprocess.run(["git", "add", "f.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                          capture_output=True, text=True).stdout.strip()

def test_create_worktree_on_namespaced_branch(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); base = _seed_repo(repo)
    wts = tmp_path / "wts"
    mgr = WorktreeManager(repo=repo, worktrees_root=wts, run_id="run-1")
    wt = mgr.create(team_id="team-01", base_sha=base)
    assert Path(wt.path).exists()
    assert (Path(wt.path) / "f.txt").read_text() == "hi"
    assert wt.branch == "cih/run-1/team-01"

def test_remove_worktree(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); base = _seed_repo(repo)
    mgr = WorktreeManager(repo=repo, worktrees_root=tmp_path / "wts", run_id="run-1")
    wt = mgr.create(team_id="team-01", base_sha=base)
    mgr.remove(wt)
    assert not Path(wt.path).exists()

def test_head_sha_reflects_commits_in_worktree(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); base = _seed_repo(repo)
    mgr = WorktreeManager(repo=repo, worktrees_root=tmp_path / "wts", run_id="run-1")
    wt = mgr.create(team_id="team-01", base_sha=base)
    (Path(wt.path) / "g.txt").write_text("new")
    subprocess.run(["git", "add", "g.txt"], cwd=wt.path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add g"], cwd=wt.path, check=True)
    assert mgr.head_sha(wt) != base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_worktree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.worktree'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/worktree.py
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from cih.safety import run_git

@dataclass
class Worktree:
    team_id: str
    path: str
    branch: str
    base_sha: str

class WorktreeManager:
    def __init__(self, repo: Path, worktrees_root: Path, run_id: str,
                 log: Optional[Callable[[str], None]] = None):
        self.repo = Path(repo)
        self.worktrees_root = Path(worktrees_root)
        self.run_id = run_id
        self.log = log

    def create(self, team_id: str, base_sha: str) -> Worktree:
        branch = f"cih/{self.run_id}/{team_id}"
        path = self.worktrees_root / self.run_id / team_id
        path.parent.mkdir(parents=True, exist_ok=True)
        run_git(["worktree", "add", "-b", branch, str(path), base_sha],
                cwd=self.repo, log=self.log)
        return Worktree(team_id=team_id, path=str(path), branch=branch, base_sha=base_sha)

    def head_sha(self, wt: Worktree) -> str:
        return run_git(["rev-parse", "HEAD"], cwd=Path(wt.path), log=self.log).strip()

    def remove(self, wt: Worktree) -> None:
        run_git(["worktree", "remove", "--force", wt.path], cwd=self.repo, log=self.log)
        # best-effort branch cleanup
        try:
            run_git(["branch", "-D", wt.branch], cwd=self.repo, log=self.log)
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_worktree.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/worktree.py tests/test_worktree.py
git commit -m "feat: git worktree manager with reserved branch namespace"
```

---

## Task 9: TDD verifier (pytest adapter)

**Files:**
- Create: `cih/tdd_verifier.py`
- Test: `tests/test_tdd_verifier.py`

Mechanically proves red→green across a (red_commit, green_commit) pair in a worktree. v1 = pytest. No adapter ⇒ `eligible=False` verdict (reviewer-only fallback). Hard-blocks obvious test weakening; routes suspicious assertion diffs to the reviewer.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tdd_verifier.py
import subprocess
from pathlib import Path
from cih.tdd_verifier import verify_tdd, TddVerdict

def _repo(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "src.py").write_text("def add(a, b):\n    raise NotImplementedError\n")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline (no tests)"], cwd=r, check=True)
    return r

def _commit(r, msg):
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=r, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=r,
                          capture_output=True, text=True).stdout.strip()

def test_clean_redgreen_passes(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert add(1, 2) == 3\n")
    red = _commit(r, "red: failing test")
    (r / "src.py").write_text("def add(a, b):\n    return a + b\n")
    green = _commit(r, "green: implement add")
    v = verify_tdd(repo=r, red_sha=red, green_sha=green,
                   test_command=["python", "-m", "pytest", "-q"],
                   declared_test_paths=["test_src.py"])
    assert isinstance(v, TddVerdict)
    assert v.eligible and v.passed
    assert v.red_failed and v.green_passed and v.full_suite_passed

def test_green_modifying_tests_is_blocked(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert add(1, 2) == 3\n")
    red = _commit(r, "red")
    # 'green' cheats by weakening the test instead of fixing src
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert True\n")
    green = _commit(r, "green: cheat")
    v = verify_tdd(repo=r, red_sha=red, green_sha=green,
                   test_command=["python", "-m", "pytest", "-q"],
                   declared_test_paths=["test_src.py"])
    assert not v.passed
    assert "green commit modified test paths" in v.reason

def test_red_that_does_not_fail_is_blocked(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text("def test_trivial():\n    assert True\n")
    red = _commit(r, "red (but passes)")
    (r / "src.py").write_text("def add(a, b):\n    return a + b\n")
    green = _commit(r, "green")
    v = verify_tdd(repo=r, red_sha=red, green_sha=green,
                   test_command=["python", "-m", "pytest", "-q"],
                   declared_test_paths=["test_src.py"])
    assert not v.passed
    assert "red commit did not fail" in v.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tdd_verifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.tdd_verifier'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/tdd_verifier.py
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from cih.safety import run_git

@dataclass
class TddVerdict:
    eligible: bool          # could we mechanically prove anything?
    passed: bool
    reason: str = ""
    red_failed: bool = False
    green_passed: bool = False
    full_suite_passed: bool = False
    suspicious_assertions: bool = False  # routed to execution-reviewer
    command: list = field(default_factory=list)
    red_sha: str = ""
    green_sha: str = ""

def _checkout(repo: Path, sha: str):
    run_git(["checkout", "-q", sha], cwd=repo)

def _run(repo: Path, cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True).returncode

def _changed_paths(repo: Path, base: str, head: str) -> list[str]:
    out = run_git(["diff", "--name-only", base, head], cwd=repo)
    return [p for p in out.splitlines() if p.strip()]

def _is_test_path(p: str, declared: list[str]) -> bool:
    name = Path(p).name
    return p in declared or name.startswith("test_") or name.endswith("_test.py")

def verify_tdd(repo: Path, red_sha: str, green_sha: str,
               test_command: list[str], declared_test_paths: list[str],
               adapter: str = "pytest") -> TddVerdict:
    repo = Path(repo)
    v = TddVerdict(eligible=(adapter == "pytest"), passed=False,
                   command=test_command, red_sha=red_sha, green_sha=green_sha)
    if not v.eligible:
        v.reason = f"no mechanical adapter for '{adapter}'; reviewer-only fallback"
        return v

    original = run_git(["rev-parse", "HEAD"], cwd=repo).strip()
    try:
        red_parent = run_git(["rev-parse", f"{red_sha}^"], cwd=repo).strip()

        # red commit must touch only test paths
        red_changes = _changed_paths(repo, red_parent, red_sha)
        if any(not _is_test_path(p, declared_test_paths) for p in red_changes):
            v.reason = "red commit changed non-test paths"
            return v

        # red commit's test command must FAIL
        _checkout(repo, red_sha)
        if _run(repo, test_command) == 0:
            v.reason = "red commit did not fail"
            return v
        v.red_failed = True

        # green commit must NOT modify any test path
        green_changes = _changed_paths(repo, red_sha, green_sha)
        if any(_is_test_path(p, declared_test_paths) for p in green_changes):
            v.reason = "green commit modified test paths"
            return v

        # obvious weakening hard-blocks; subtle ones flagged for reviewer
        red_test_blob = "\n".join(
            run_git(["show", f"{red_sha}:{p}"], cwd=repo)
            for p in red_changes if _is_test_path(p, declared_test_paths))
        if "@pytest.mark.skip" in red_test_blob or "pytest.skip(" in red_test_blob:
            v.reason = "test introduces skip markers"
            return v
        if "assert True" in red_test_blob:
            v.suspicious_assertions = True  # routed to reviewer, not hard-failed

        # green commit's test command must PASS, and full suite must pass
        _checkout(repo, green_sha)
        if _run(repo, test_command) != 0:
            v.reason = "green commit did not pass the declared test command"
            return v
        v.green_passed = True
        if _run(repo, ["python", "-m", "pytest", "-q"]) != 0:
            v.reason = "full suite failed at green commit"
            return v
        v.full_suite_passed = True

        v.passed = True
        v.reason = "red->green verified"
        return v
    finally:
        _checkout(repo, original)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tdd_verifier.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/tdd_verifier.py tests/test_tdd_verifier.py
git commit -m "feat: mechanical pytest TDD verifier with reviewer fallback"
```

---

## Task 10: Attempt records + transition table

**Files:**
- Create: `cih/attempts.py`
- Test: `tests/test_attempts.py`

Distinguishes plan/execution/integration/final-reject; enforces global per-team attempt cap.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_attempts.py
import pytest
from cih.attempts import AttemptLog, AttemptKind, AttemptCapExceeded

def test_records_attempts_and_marks_current():
    log = AttemptLog(team_id="team-01", cap=4)
    a1 = log.start(kind=AttemptKind.EXECUTION, base_sha="aaa",
                   branch="cih/r/team-01", worktree_path="/wt", feedback="")
    assert log.current().attempt_id == a1.attempt_id
    a2 = log.start(kind=AttemptKind.PLAN, base_sha="aaa",
                   branch="cih/r/team-01", worktree_path="/wt",
                   feedback="reviewer said scope wrong", parent=a1.attempt_id)
    assert log.current().attempt_id == a2.attempt_id
    assert a2.parent_attempt_id == a1.attempt_id
    assert len(log.all()) == 2  # failed attempts preserved

def test_cap_enforced_across_all_kinds():
    log = AttemptLog(team_id="team-01", cap=2)
    log.start(kind=AttemptKind.EXECUTION, base_sha="a", branch="b",
              worktree_path="/w", feedback="")
    log.start(kind=AttemptKind.INTEGRATION, base_sha="a", branch="b",
              worktree_path="/w", feedback="")
    with pytest.raises(AttemptCapExceeded):
        log.start(kind=AttemptKind.EXECUTION, base_sha="a", branch="b",
                  worktree_path="/w", feedback="")

def test_serialization_roundtrip():
    log = AttemptLog(team_id="team-01", cap=4)
    log.start(kind=AttemptKind.EXECUTION, base_sha="a", branch="b",
              worktree_path="/w", feedback="")
    restored = AttemptLog.from_dict(log.to_dict())
    assert restored.current().base_sha == "a"
    assert restored.cap == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_attempts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.attempts'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/attempts.py
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Optional

class AttemptKind(str, Enum):
    PLAN = "plan_retry"
    EXECUTION = "execution_retry"
    INTEGRATION = "integration_retry"
    FINAL_REJECT = "final_reject"

class AttemptCapExceeded(Exception):
    pass

@dataclass
class Attempt:
    attempt_id: str
    kind: str
    base_sha: str
    branch: str
    worktree_path: str
    feedback_input: str
    parent_attempt_id: Optional[str] = None
    is_current: bool = True

class AttemptLog:
    def __init__(self, team_id: str, cap: int):
        self.team_id = team_id
        self.cap = cap
        self._attempts: list[Attempt] = []

    def start(self, kind: AttemptKind, base_sha: str, branch: str,
              worktree_path: str, feedback: str,
              parent: Optional[str] = None) -> Attempt:
        if len(self._attempts) >= self.cap:
            raise AttemptCapExceeded(
                f"{self.team_id}: attempt cap {self.cap} reached")
        for a in self._attempts:
            a.is_current = False
        att = Attempt(
            attempt_id=f"attempt-{len(self._attempts)+1:02d}",
            kind=kind.value if isinstance(kind, AttemptKind) else kind,
            base_sha=base_sha, branch=branch, worktree_path=worktree_path,
            feedback_input=feedback, parent_attempt_id=parent)
        self._attempts.append(att)
        return att

    def current(self) -> Optional[Attempt]:
        return self._attempts[-1] if self._attempts else None

    def all(self) -> list[Attempt]:
        return list(self._attempts)

    def to_dict(self) -> dict:
        return {"team_id": self.team_id, "cap": self.cap,
                "attempts": [asdict(a) for a in self._attempts]}

    @classmethod
    def from_dict(cls, d: dict) -> "AttemptLog":
        log = cls(team_id=d["team_id"], cap=d["cap"])
        log._attempts = [Attempt(**a) for a in d["attempts"]]
        return log
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_attempts.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/attempts.py tests/test_attempts.py
git commit -m "feat: typed attempt records with global per-team cap"
```

---

## Task 11: Agent contracts + output validation

**Files:**
- Create: `cih/contracts.py`
- Test: `tests/test_contracts.py`

A role = prompt + I/O JSON Schema + allowed tools + version. Output is validated by shared code; invalid output raises (caller retries).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contracts.py
import pytest
from cih.contracts import AgentContract, OutputValidationError

PLAN_OUT = {
    "type": "object",
    "required": ["tasks"],
    "properties": {"tasks": {"type": "array", "items": {"type": "string"}}},
}

def test_contract_validates_good_output():
    c = AgentContract(role="planner", agent_version="1.0.0",
                      role_prompt="Plan it.", input_schema={"type": "object"},
                      output_schema=PLAN_OUT, allowed_tools=["Read"])
    c.validate_output({"tasks": ["a", "b"]})  # no raise

def test_contract_rejects_bad_output():
    c = AgentContract(role="planner", agent_version="1.0.0",
                      role_prompt="Plan it.", input_schema={"type": "object"},
                      output_schema=PLAN_OUT, allowed_tools=["Read"])
    with pytest.raises(OutputValidationError):
        c.validate_output({"tasks": "not-a-list"})

def test_version_hash_is_stable():
    c1 = AgentContract(role="planner", agent_version="1.0.0",
                       role_prompt="Plan it.", input_schema={"type": "object"},
                       output_schema=PLAN_OUT, allowed_tools=["Read"])
    c2 = AgentContract(role="planner", agent_version="1.0.0",
                       role_prompt="Plan it.", input_schema={"type": "object"},
                       output_schema=PLAN_OUT, allowed_tools=["Read"])
    assert c1.prompt_hash() == c2.prompt_hash()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.contracts'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/contracts.py
import hashlib
import json
from dataclasses import dataclass, field
from jsonschema import validate, ValidationError

class OutputValidationError(Exception):
    pass

@dataclass
class AgentContract:
    role: str
    agent_version: str
    role_prompt: str
    input_schema: dict
    output_schema: dict
    allowed_tools: list = field(default_factory=list)
    runtime_adapter_settings: dict = field(default_factory=dict)

    def validate_output(self, output: dict) -> None:
        try:
            validate(instance=output, schema=self.output_schema)
        except ValidationError as e:
            raise OutputValidationError(f"{self.role} output invalid: {e.message}") from e

    def prompt_hash(self) -> str:
        blob = json.dumps({"prompt": self.role_prompt, "in": self.input_schema,
                           "out": self.output_schema, "v": self.agent_version},
                          sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_contracts.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/contracts.py tests/test_contracts.py
git commit -m "feat: versioned agent contracts with shared output validation"
```

---

## Task 12: Agent runner abstraction (stubbable)

**Files:**
- Create: `cih/agents.py`
- Test: `tests/test_agents.py`

An `AgentRunner` protocol: `StubRunner` for tests, `ClaudeCliRunner` for headless. Both validate output against the contract.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents.py
import pytest
from cih.contracts import AgentContract, OutputValidationError
from cih.agents import StubRunner, invoke

OUT = {"type": "object", "required": ["ok"],
       "properties": {"ok": {"type": "boolean"}}}

def _contract():
    return AgentContract(role="planner", agent_version="1.0.0",
                         role_prompt="p", input_schema={"type": "object"},
                         output_schema=OUT, allowed_tools=[])

def test_invoke_returns_validated_output():
    runner = StubRunner(responses={"planner": {"ok": True}})
    out = invoke(runner, _contract(), {"charter": "x"})
    assert out == {"ok": True}

def test_invoke_raises_on_schema_violation():
    runner = StubRunner(responses={"planner": {"ok": "nope"}})
    with pytest.raises(OutputValidationError):
        invoke(runner, _contract(), {"charter": "x"})

def test_stub_records_calls():
    runner = StubRunner(responses={"planner": {"ok": True}})
    invoke(runner, _contract(), {"charter": "x"})
    assert runner.calls[0]["role"] == "planner"
    assert runner.calls[0]["input"] == {"charter": "x"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.agents'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/agents.py
import json
import subprocess
from typing import Protocol
from cih.contracts import AgentContract

class AgentRunner(Protocol):
    def run(self, contract: AgentContract, input_data: dict) -> dict: ...

class StubRunner:
    """Test double: returns canned responses keyed by role."""
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[dict] = []

    def run(self, contract: AgentContract, input_data: dict) -> dict:
        self.calls.append({"role": contract.role, "input": input_data})
        if contract.role not in self.responses:
            raise KeyError(f"no stub response for role {contract.role}")
        return self.responses[contract.role]

class ClaudeCliRunner:
    """Headless adapter: drives `claude -p --append-system-prompt`.

    Flags precede the prompt; output is expected as JSON on stdout.
    """
    def __init__(self, cwd: str, extra_args: list[str] | None = None):
        self.cwd = cwd
        self.extra_args = extra_args or []

    def run(self, contract: AgentContract, input_data: dict) -> dict:
        prompt = json.dumps(input_data)
        cmd = ["claude", "-p", "--output-format", "json",
               "--append-system-prompt", contract.role_prompt,
               *self.extra_args, "--", prompt]
        proc = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"claude failed for {contract.role}: {proc.stderr}")
        envelope = json.loads(proc.stdout)
        # claude -p --output-format json wraps content in {"result": "..."}
        result = envelope.get("result", envelope)
        return result if isinstance(result, dict) else json.loads(result)

def invoke(runner: AgentRunner, contract: AgentContract, input_data: dict) -> dict:
    output = runner.run(contract, input_data)
    contract.validate_output(output)
    return output
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/agents.py tests/test_agents.py
git commit -m "feat: agent runner abstraction (stub + claude-cli) with validation"
```

---

## Task 13: Define the six agent contracts

**Files:**
- Create: `cih/roles.py`
- Create: `.claude/agents/high-planner.md`, `planner.md`, `plan-reviewer.md`, `executor.md`, `execution-reviewer.md` (orchestrator has no prompt — it is code)
- Test: `tests/test_roles.py`

Contracts load their prompt body from `.claude/agents/<role>.md`, giving one source of truth for both runtimes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roles.py
from cih.roles import load_contracts, ROLE_NAMES

def test_all_roles_load_with_prompt_bodies():
    contracts = load_contracts()
    assert set(contracts) == set(ROLE_NAMES)
    for name, c in contracts.items():
        assert c.role == name
        assert len(c.role_prompt.strip()) > 20      # real prompt body present
        assert c.output_schema["type"] == "object"

def test_planner_output_schema_requires_tasks():
    c = load_contracts()["planner"]
    assert "tasks" in c.output_schema["required"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.roles'`

- [ ] **Step 3: Create the agent prompt files**

Create `.claude/agents/high-planner.md`:

```markdown
---
name: high-planner
description: Audits a target repo and decomposes high-value improvements into parallel team charters.
---
You are the HIGH-PLANNER. Given a target repo path, user focus areas, and the current
opportunity ledger, audit the codebase by reading code and reasoning about bugs, smells,
missing tests, and unclear boundaries. Produce a ranked list of improvement opportunities,
each with value/confidence/effort/risk scores and a rationale. Group independent ones into
team charters; each charter has a goal and an impact manifest (intended_files, intended_apis,
intended_tests, dependencies, parallelization_exclusions). Charters must not overlap on files.
Return JSON only, matching the output schema.
```

Create `.claude/agents/planner.md`:

```markdown
---
name: planner
description: Turns one team charter into an ordered TDD task plan with testable acceptance criteria.
---
You are the PLANNER. Given one charter and its impact manifest, produce an ordered list of
bite-sized tasks. Every task must have a testable acceptance criterion and name the test file
and test command. Plans must be TDD-shaped: a failing test precedes its implementation.
Return JSON only, matching the output schema.
```

Create `.claude/agents/plan-reviewer.md`:

```markdown
---
name: plan-reviewer
description: Skeptically reviews a task plan for scope, testability, TDD feasibility, conflict risk.
---
You are the PLAN-REVIEWER. Skeptically assess the plan against its charter: is the scope
correct, are acceptance criteria genuinely testable, is each task TDD-feasible, and is there
file-conflict risk with the impact manifest? Return JSON only: {approved: bool, feedback: str}.
Default to NOT approved if criteria are vague or untestable.
```

Create `.claude/agents/executor.md`:

```markdown
---
name: executor
description: Implements a reviewed plan in a git worktree using strict red-green TDD.
---
You are the EXECUTOR. Work ONLY inside the provided worktree path. For each task: write the
failing test and commit it (red), then implement the minimal code to pass and commit it
(green). The green commit must NOT modify test files. Stage only the files you changed via the
provided staging wrapper — never `git add -A`. Return JSON only: a list of {task, red_sha,
green_sha, test_command, declared_test_paths}.
```

Create `.claude/agents/execution-reviewer.md`:

```markdown
---
name: execution-reviewer
description: Skeptical QA that judges executed work on top of a green mechanical TDD verdict.
---
You are the EXECUTION-REVIEWER, a separate skeptical QA session. You are given the plan,
acceptance criteria, the mechanical TDD verdict, and any suspicious-assertion flags. Confirm
each acceptance criterion is genuinely met, no regressions were introduced, and any flagged
assertion diffs are legitimate. Return JSON only: {approved: bool, reasons: [str]}.
```

- [ ] **Step 4: Write `cih/roles.py`**

```python
# cih/roles.py
import re
from pathlib import Path
from cih.contracts import AgentContract

ROLE_NAMES = ["high-planner", "planner", "plan-reviewer", "executor", "execution-reviewer"]

_AGENTS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "agents"

_OUTPUT_SCHEMAS = {
    "high-planner": {
        "type": "object", "required": ["opportunities", "charters"],
        "properties": {
            "opportunities": {"type": "array"},
            "charters": {"type": "array"},
        },
    },
    "planner": {
        "type": "object", "required": ["tasks"],
        "properties": {"tasks": {"type": "array"}},
    },
    "plan-reviewer": {
        "type": "object", "required": ["approved", "feedback"],
        "properties": {"approved": {"type": "boolean"},
                       "feedback": {"type": "string"}},
    },
    "executor": {
        "type": "object", "required": ["commits"],
        "properties": {"commits": {"type": "array"}},
    },
    "execution-reviewer": {
        "type": "object", "required": ["approved", "reasons"],
        "properties": {"approved": {"type": "boolean"},
                       "reasons": {"type": "array"}},
    },
}

def _strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL).strip()

def load_contracts(agents_dir: Path = _AGENTS_DIR) -> dict[str, AgentContract]:
    contracts = {}
    for name in ROLE_NAMES:
        body = _strip_frontmatter((agents_dir / f"{name}.md").read_text())
        contracts[name] = AgentContract(
            role=name, agent_version="1.0.0", role_prompt=body,
            input_schema={"type": "object"},
            output_schema=_OUTPUT_SCHEMAS[name], allowed_tools=[])
    return contracts
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_roles.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add cih/roles.py .claude/agents/ tests/test_roles.py
git commit -m "feat: six agent role contracts loaded from .claude/agents"
```

---

## Task 14: Per-team pipeline

**Files:**
- Create: `cih/team.py`
- Test: `tests/test_team.py`

Runs planner → plan-reviewer (≤retries) → executor → tdd_verifier → execution-reviewer (≤retries) using injected runner + verifier callables (so it's testable with stubs).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team.py
from cih.team import run_team, TeamResult
from cih.agents import StubRunner
from cih.contracts import AgentContract
from cih.tdd_verifier import TddVerdict

def _contracts():
    def c(role, out):
        return AgentContract(role=role, agent_version="1", role_prompt="p",
                             input_schema={"type": "object"}, output_schema=out)
    return {
        "planner": c("planner", {"type": "object", "required": ["tasks"],
                                 "properties": {"tasks": {"type": "array"}}}),
        "plan-reviewer": c("plan-reviewer", {"type": "object",
            "required": ["approved", "feedback"],
            "properties": {"approved": {"type": "boolean"},
                           "feedback": {"type": "string"}}}),
        "executor": c("executor", {"type": "object", "required": ["commits"],
                                   "properties": {"commits": {"type": "array"}}}),
        "execution-reviewer": c("execution-reviewer", {"type": "object",
            "required": ["approved", "reasons"],
            "properties": {"approved": {"type": "boolean"},
                           "reasons": {"type": "array"}}}),
    }

def _green_verifier(**kwargs):
    return TddVerdict(eligible=True, passed=True, red_failed=True,
                      green_passed=True, full_suite_passed=True)

def test_happy_path_team_passes():
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": [{"task": "t1", "red_sha": "r", "green_sha": "g",
                                  "test_command": ["pytest"], "declared_test_paths": ["t.py"]}]},
        "execution-reviewer": {"approved": True, "reasons": ["ok"]},
    })
    result = run_team(charter={"id": "team-01", "goal": "x"}, contracts=_contracts(),
                      runner=runner, verifier=_green_verifier,
                      plan_review_retries=2, exec_review_retries=2, attempt_cap=4)
    assert isinstance(result, TeamResult)
    assert result.passed

def test_team_fails_when_tdd_verifier_blocks():
    def red_verifier(**kwargs):
        return TddVerdict(eligible=True, passed=False, reason="red commit did not fail")
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": [{"task": "t1", "red_sha": "r", "green_sha": "g",
                                  "test_command": ["pytest"], "declared_test_paths": ["t.py"]}]},
        "execution-reviewer": {"approved": True, "reasons": ["ok"]},
    })
    result = run_team(charter={"id": "team-01", "goal": "x"}, contracts=_contracts(),
                      runner=runner, verifier=red_verifier,
                      plan_review_retries=1, exec_review_retries=1, attempt_cap=4)
    assert not result.passed
    assert "tdd" in result.reason.lower()

def test_plan_rejection_triggers_replan_then_gives_up():
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": False, "feedback": "too vague"},
        "executor": {"commits": []},
        "execution-reviewer": {"approved": True, "reasons": []},
    })
    result = run_team(charter={"id": "team-01", "goal": "x"}, contracts=_contracts(),
                      runner=runner, verifier=_green_verifier,
                      plan_review_retries=2, exec_review_retries=2, attempt_cap=10)
    assert not result.passed
    assert "plan" in result.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_team.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.team'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/team.py
from dataclasses import dataclass, field
from typing import Callable
from cih.agents import invoke

@dataclass
class TeamResult:
    team_id: str
    passed: bool
    reason: str = ""
    plan: dict = field(default_factory=dict)
    commits: list = field(default_factory=list)
    tdd_verdicts: list = field(default_factory=list)

def run_team(charter: dict, contracts: dict, runner, verifier: Callable,
             plan_review_retries: int, exec_review_retries: int,
             attempt_cap: int) -> TeamResult:
    team_id = charter["id"]

    # plan + plan-review loop
    plan, feedback = None, ""
    approved = False
    for _ in range(plan_review_retries + 1):
        plan = invoke(runner, contracts["planner"],
                      {"charter": charter, "feedback": feedback})
        review = invoke(runner, contracts["plan-reviewer"],
                        {"charter": charter, "plan": plan})
        if review["approved"]:
            approved = True
            break
        feedback = review["feedback"]
    if not approved:
        return TeamResult(team_id, False, "plan never approved by plan-reviewer", plan=plan)

    # execute + verify + execution-review loop
    reason = "exec never approved"
    for _ in range(exec_review_retries + 1):
        execution = invoke(runner, contracts["executor"],
                           {"charter": charter, "plan": plan})
        commits = execution["commits"]
        # call the verifier with ONLY its declared params (commit dicts also carry "task")
        verdicts = [verifier(red_sha=c["red_sha"], green_sha=c["green_sha"],
                             test_command=c["test_command"],
                             declared_test_paths=c["declared_test_paths"])
                    for c in commits] if commits else []
        if any(v.eligible and not v.passed for v in verdicts):
            bad = next(v for v in verdicts if v.eligible and not v.passed)
            reason = f"tdd verifier blocked: {bad.reason}"
            continue
        suspicious = any(getattr(v, "suspicious_assertions", False) for v in verdicts)
        review = invoke(runner, contracts["execution-reviewer"],
                        {"charter": charter, "plan": plan, "commits": commits,
                         "tdd_verdicts": [v.__dict__ for v in verdicts],
                         "suspicious_assertions": suspicious})
        if review["approved"]:
            return TeamResult(team_id, True, "passed", plan=plan,
                              commits=commits, tdd_verdicts=verdicts)
        reason = "execution-reviewer rejected: " + "; ".join(review["reasons"])
    return TeamResult(team_id, False, reason, plan=plan)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_team.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/team.py tests/test_team.py
git commit -m "feat: per-team pipeline with bounded plan/exec review loops"
```

---

## Task 15: Bounded merge queue

**Files:**
- Create: `cih/merge_queue.py`
- Test: `tests/test_merge_queue.py`

Integrates passed teams sequentially against a live base, with manifest-based overlap prechecks and bounded integration retries (re-verify via an injected callable).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_merge_queue.py
from cih.merge_queue import order_by_overlap, integrate, MergeOutcome

def _charter(cid, files):
    return {"id": cid, "impact_manifest": {"intended_files": files}}

def test_order_puts_low_overlap_first():
    charters = [_charter("a", ["x.py", "y.py"]), _charter("b", ["z.py"])]
    ordered = order_by_overlap(charters)
    assert ordered[0]["id"] == "b"  # fewer files / less overlap risk first

def test_integrate_merges_all_when_reverify_passes():
    teams = [("a", _charter("a", ["x.py"])), ("b", _charter("b", ["y.py"]))]
    log = []
    def reverify(team_id, base):  # always green
        log.append(team_id); return True
    outcome = integrate(teams, base_sha="base", reverify=reverify,
                        integration_retries=2)
    assert isinstance(outcome, MergeOutcome)
    assert outcome.merged == ["a", "b"]
    assert outcome.rejected == []

def test_integrate_rejects_after_retry_budget():
    teams = [("a", _charter("a", ["x.py"]))]
    calls = {"n": 0}
    def reverify(team_id, base):
        calls["n"] += 1
        return False  # never passes
    outcome = integrate(teams, base_sha="base", reverify=reverify,
                        integration_retries=2)
    assert outcome.merged == []
    assert outcome.rejected == ["a"]
    assert calls["n"] == 3  # initial + 2 retries, bounded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_merge_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.merge_queue'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/merge_queue.py
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class MergeOutcome:
    merged: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    final_base_sha: str = ""

def order_by_overlap(charters: list[dict]) -> list[dict]:
    # cheap precheck: fewer intended files -> integrate earlier (less collision surface)
    return sorted(charters,
                  key=lambda c: len(c.get("impact_manifest", {}).get("intended_files", [])))

def integrate(teams: list[tuple], base_sha: str, reverify: Callable[[str, str], bool],
              integration_retries: int) -> MergeOutcome:
    """teams: list of (team_id, charter). reverify(team_id, base)->bool re-runs the
    full suite + execution-reviewer on the rebased branch."""
    ordered_ids = [c["id"] for c in order_by_overlap([c for _, c in teams])]
    by_id = dict(teams)
    outcome = MergeOutcome(final_base_sha=base_sha)
    for team_id in ordered_ids:
        passed = False
        for _ in range(integration_retries + 1):
            if reverify(team_id, outcome.final_base_sha):
                passed = True
                break
        if passed:
            outcome.merged.append(team_id)
            outcome.final_base_sha = f"{outcome.final_base_sha}+{team_id}"
        else:
            outcome.rejected.append(team_id)
    return outcome
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_merge_queue.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/merge_queue.py tests/test_merge_queue.py
git commit -m "feat: bounded merge queue with overlap prechecks and re-verify budget"
```

---

## Task 16: Orchestrator run loop + termination

**Files:**
- Create: `cih/orchestrator.py`
- Test: `tests/test_orchestrator.py`

Drives iterations in both modes using injected `high_planner_fn` and `team_runner_fn` (stubbed in tests). Persists `run.json`, `ledger.json`, per-iteration artifacts.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
from pathlib import Path
from cih.config import RunConfig
from cih.orchestrator import Orchestrator, IterationResult

def _cfg(tmp_path, **over):
    t = tmp_path / "target"; s = tmp_path / "state"; t.mkdir(); s.mkdir()
    base = dict(mode="fixed-N", iterations=2, target_repo=str(t), state_dir=str(s))
    base.update(over)
    return RunConfig.create(**base)

def test_fixed_n_runs_exactly_n_iterations(tmp_path):
    cfg = _cfg(tmp_path, iterations=3)
    calls = {"n": 0}
    def high_planner(ctx):
        calls["n"] += 1
        return {"opportunities": [], "charters": []}
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=lambda *a, **k: [])
    summary = orch.run()
    assert calls["n"] == 3
    assert summary["iterations_run"] == 3
    assert Path(cfg.state_dir, "run.json").exists()

def test_until_converged_stops_after_dry_streak(tmp_path):
    cfg = _cfg(tmp_path, mode="until-converged", iterations=None,
               convergence_dry_streak=2, max_iterations=10)
    def high_planner(ctx):
        return {"opportunities": [], "charters": []}  # always dry
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=lambda *a, **k: [])
    summary = orch.run()
    assert summary["iterations_run"] == 2  # two consecutive dry iters
    assert summary["stopped_reason"] == "converged"

def test_max_iterations_caps_until_converged(tmp_path):
    cfg = _cfg(tmp_path, mode="until-converged", iterations=None,
               convergence_dry_streak=99, max_iterations=4)
    def high_planner(ctx):
        # always offers a high-value opportunity -> never dry
        return {"opportunities": [{"title": "x", "scope": "s", "value": 0.9,
                "confidence": 0.9, "effort": 0.1, "risk": 0.1, "rationale": "r"}],
                "charters": []}
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=lambda *a, **k: [])
    summary = orch.run()
    assert summary["iterations_run"] == 4
    assert summary["stopped_reason"] == "max_iterations"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.orchestrator'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator run loop with fixed-N and until-converged termination"
```

---

## Task 17: resume() reconciliation

**Files:**
- Modify: `cih/orchestrator.py` (add `resume` classmethod + reconciliation)
- Test: `tests/test_resume.py`

Reconciles persisted state against git ground truth before continuing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resume.py
from pathlib import Path
from cih.config import RunConfig
from cih.orchestrator import Orchestrator, reconcile

def _cfg(tmp_path):
    t = tmp_path / "target"; s = tmp_path / "state"; t.mkdir(); s.mkdir()
    return RunConfig.create(mode="fixed-N", iterations=2,
                            target_repo=str(t), state_dir=str(s))

def test_reconcile_flags_missing_run_json(tmp_path):
    cfg = _cfg(tmp_path)
    report = reconcile(cfg, run_id="run-1")
    assert report["resumable"] is False
    assert "run.json missing" in report["issues"]

def test_reconcile_ok_after_a_run(tmp_path):
    cfg = _cfg(tmp_path)
    Orchestrator(cfg, high_planner_fn=lambda ctx: {"opportunities": [], "charters": []},
                 team_runner_fn=lambda *a, **k: []).run()
    report = reconcile(cfg, run_id="run-1")
    assert report["resumable"] is True
    assert report["issues"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_resume.py -v`
Expected: FAIL — `ImportError: cannot import name 'reconcile'`

- [ ] **Step 3: Add the implementation to `cih/orchestrator.py`**

Append to `cih/orchestrator.py`:

```python
def reconcile(cfg: RunConfig, run_id: str) -> dict:
    """Compare persisted state against ground truth before resuming."""
    issues = []
    state_dir = Path(cfg.state_dir)
    run_json = state_dir / "run.json"
    if not run_json.exists():
        issues.append("run.json missing")
    if not Path(cfg.target_repo).exists():
        issues.append("target_repo missing")
    return {"resumable": not issues, "issues": issues}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_resume.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/orchestrator.py tests/test_resume.py
git commit -m "feat: resume() reconciliation against ground truth"
```

---

## Task 18: Headless CLI runner

**Files:**
- Create: `cih/runner.py`
- Test: `tests/test_runner_cli.py`

Wires config → orchestrator → real runners. CLI is thin and testable via `build_orchestrator`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner_cli.py
from pathlib import Path
from cih.runner import parse_args, build_config

def test_parse_args_fixed_n(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "fixed-N", "--iterations", "3",
                     "--target-repo", str(t), "--state-dir", str(s),
                     "--focus", "tests", "--focus", "perf"])
    cfg = build_config(ns)
    assert cfg.mode == "fixed-N"
    assert cfg.iterations == 3
    assert cfg.focus_areas == ["tests", "perf"]

def test_parse_args_until_converged(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "until-converged",
                     "--target-repo", str(t), "--state-dir", str(s)])
    cfg = build_config(ns)
    assert cfg.mode == "until-converged"
    assert cfg.iterations is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_runner_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.runner'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/runner.py
import argparse
import sys
from cih.config import RunConfig

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cih", description="Continuous Improvement Harness")
    p.add_argument("--mode", required=True, choices=["fixed-N", "until-converged"])
    p.add_argument("--iterations", type=int, default=None)
    p.add_argument("--target-repo", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--focus", action="append", default=[], dest="focus_areas")
    p.add_argument("--max-iterations", type=int, default=25)
    return p.parse_args(argv)

def build_config(ns: argparse.Namespace) -> RunConfig:
    return RunConfig.create(
        mode=ns.mode, iterations=ns.iterations, target_repo=ns.target_repo,
        state_dir=ns.state_dir, focus_areas=ns.focus_areas,
        max_iterations=ns.max_iterations)

def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv if argv is not None else sys.argv[1:])
    cfg = build_config(ns)
    # Real wiring (orchestrator + ClaudeCliRunner + worktree/merge integration) is
    # assembled here; see Task 19 for the integration glue.
    print(f"cih: mode={cfg.mode} target={cfg.target_repo} state={cfg.state_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_runner_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/runner.py tests/test_runner_cli.py
git commit -m "feat: headless CLI arg parsing and config build"
```

---

## Task 19: Integration glue — real team runner

**Files:**
- Create: `cih/integration.py`
- Modify: `cih/runner.py:main` (use real `team_runner_fn`)
- Test: `tests/test_integration_glue.py`

Binds `run_team` + worktree manager + `tdd_verifier` + `merge_queue` into the `team_runner_fn` the orchestrator calls. Tested with a stub runner against a real throwaway git repo.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_integration_glue.py
import subprocess
from pathlib import Path
from cih.integration import make_team_runner
from cih.agents import StubRunner
from cih.roles import load_contracts
from cih.tdd_verifier import TddVerdict

def _seed_repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                          capture_output=True, text=True).stdout.strip()

def test_team_runner_runs_charters_and_returns_results(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); base = _seed_repo(repo)
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": [{"task": "t1", "red_sha": "r", "green_sha": "g",
                     "test_command": ["true"], "declared_test_paths": ["t.py"]}]},
        "execution-reviewer": {"approved": True, "reasons": ["ok"]},
    })
    team_runner = make_team_runner(
        contracts=load_contracts(), runner=runner,
        verifier=lambda **k: TddVerdict(eligible=True, passed=True),
        repo=repo, worktrees_root=tmp_path / "wts", run_id="run-1", base_sha=base,
        plan_review_retries=1, exec_review_retries=1, attempt_cap=4)
    charters = [{"id": "team-01", "goal": "g", "impact_manifest": {"intended_files": ["a.py"]}}]
    results = team_runner(charters, {"iteration": 1})
    assert len(results) == 1
    assert results[0].team_id == "team-01"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_integration_glue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.integration'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/integration.py
from pathlib import Path
from typing import Callable
from cih.team import run_team
from cih.worktree import WorktreeManager

def make_team_runner(contracts: dict, runner, verifier: Callable, repo: Path,
                     worktrees_root: Path, run_id: str, base_sha: str,
                     plan_review_retries: int, exec_review_retries: int,
                     attempt_cap: int) -> Callable:
    mgr = WorktreeManager(repo=repo, worktrees_root=worktrees_root, run_id=run_id)

    def team_runner(charters: list[dict], ctx: dict) -> list:
        results = []
        for charter in charters:
            wt = mgr.create(team_id=charter["id"], base_sha=base_sha)
            try:
                result = run_team(
                    charter=charter, contracts=contracts, runner=runner,
                    verifier=verifier, plan_review_retries=plan_review_retries,
                    exec_review_retries=exec_review_retries, attempt_cap=attempt_cap)
                results.append(result)
            finally:
                if not any(r.passed for r in results if r.team_id == charter["id"]):
                    mgr.remove(wt)
        return results

    return team_runner
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_integration_glue.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/integration.py tests/test_integration_glue.py
git commit -m "feat: integration glue binding teams, worktrees, and verifier"
```

---

## Task 20: Conformance tests for all roles (both runtimes)

**Files:**
- Test: `tests/test_conformance.py`

Asserts every role's contract validates a canned schema-valid response — the shared validator both runtimes rely on.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conformance.py
import pytest
from cih.roles import load_contracts, ROLE_NAMES
from cih.agents import StubRunner, invoke

CANNED = {
    "high-planner": {"opportunities": [], "charters": []},
    "planner": {"tasks": ["t1"]},
    "plan-reviewer": {"approved": True, "feedback": "ok"},
    "executor": {"commits": []},
    "execution-reviewer": {"approved": True, "reasons": ["ok"]},
}

@pytest.mark.parametrize("role", ROLE_NAMES)
def test_canned_response_is_schema_valid(role):
    contracts = load_contracts()
    runner = StubRunner(responses={role: CANNED[role]})
    out = invoke(runner, contracts[role], {"any": "input"})
    assert out == CANNED[role]

def test_bad_response_rejected_for_every_role():
    from cih.contracts import OutputValidationError
    contracts = load_contracts()
    runner = StubRunner(responses={r: {"garbage": True} for r in ROLE_NAMES})
    for role in ROLE_NAMES:
        with pytest.raises(OutputValidationError):
            invoke(runner, contracts[role], {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_conformance.py -v`
Expected: FAIL initially if any schema is wrong; fix schemas in `cih/roles.py` until green.

- [ ] **Step 3: Reconcile any schema mismatches**

If a parametrized case fails, adjust the corresponding `_OUTPUT_SCHEMAS` entry in `cih/roles.py` so the canned response validates. (No new code beyond schema tweaks.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_conformance.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_conformance.py cih/roles.py
git commit -m "test: conformance for all role contracts"
```

---

## Task 21: End-to-end integration smoke test

**Files:**
- Test: `tests/test_e2e_smoke.py`

One full fixed-N run against a tiny throwaway git repo, all agents stubbed — proves the orchestrator → team_runner → worktree path holds together and writes state.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_e2e_smoke.py
import subprocess
from pathlib import Path
from cih.config import RunConfig
from cih.orchestrator import Orchestrator
from cih.integration import make_team_runner
from cih.agents import StubRunner
from cih.roles import load_contracts
from cih.tdd_verifier import TddVerdict

def _seed_repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                          capture_output=True, text=True).stdout.strip()

def test_full_fixed_n_run_writes_state(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); base = _seed_repo(repo)
    state = tmp_path / "state"; state.mkdir()
    cfg = RunConfig.create(mode="fixed-N", iterations=2,
                           target_repo=str(repo), state_dir=str(state))
    runner = StubRunner(responses={
        "high-planner": {"opportunities": [], "charters": [
            {"id": "team-01", "goal": "g", "impact_manifest": {"intended_files": ["a.py"]}}]},
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": []},
        "execution-reviewer": {"approved": True, "reasons": ["ok"]},
    })
    contracts = load_contracts()
    team_runner = make_team_runner(
        contracts=contracts, runner=runner,
        verifier=lambda **k: TddVerdict(eligible=True, passed=True),
        repo=repo, worktrees_root=tmp_path / "wts", run_id="run-1", base_sha=base,
        plan_review_retries=1, exec_review_retries=1, attempt_cap=4)

    def high_planner(ctx):
        from cih.agents import invoke
        return invoke(runner, contracts["high-planner"], ctx)

    orch = Orchestrator(cfg, high_planner_fn=high_planner, team_runner_fn=team_runner)
    summary = orch.run()
    assert summary["iterations_run"] == 2
    assert (state / "run.json").exists()
    assert (state / "iterations" / "iter-001" / "audit.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_e2e_smoke.py -v`
Expected: FAIL initially (any wiring mismatch surfaces here).

- [ ] **Step 3: Fix wiring mismatches**

Resolve any import/signature mismatches surfaced by the smoke test. No new components — only glue corrections.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all modules green)

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_smoke.py
git commit -m "test: end-to-end fixed-N smoke run with stubbed agents"
```

---

## Task 22: Claude Code skill (interactive entry point)

**Files:**
- Create: `.claude/skills/cih/SKILL.md`
- Test: `tests/test_skill_doc.py`

The skill renders the same contracts and uses the Agent/Task tools instead of `claude -p`. The doc encodes the orchestration steps; a lightweight test asserts the doc references each role and the safety invariants.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_doc.py
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "cih" / "SKILL.md"

def test_skill_doc_mentions_all_roles_and_invariants():
    text = SKILL.read_text().lower()
    for role in ["high-planner", "planner", "plan-reviewer", "executor", "execution-reviewer"]:
        assert role in text
    assert "worktree" in text
    assert "never" in text and "push" in text          # no-push invariant documented
    assert "git add -a" in text or "git add -a is" in text or "add -a" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_doc.py -v`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Write the skill doc**

Create `.claude/skills/cih/SKILL.md`:

```markdown
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
   `cih/<run_id>/team-NN`):
   - **planner** → task plan with testable acceptance criteria
   - **plan-reviewer** → approve/reject (bounded re-plan)
   - **executor** → red-green TDD commits in the worktree
   - mechanical **tdd_verifier** (pytest) → green required before review
   - **execution-reviewer** → approve/reject (bounded retry)
3. Integrate PASSED teams through the bounded **merge queue**: rebase onto the live base,
   re-run the full suite + execution-reviewer, then fast-forward.
4. Record `audit.json`, `teams.json`, per-team artifacts, `iteration.md`, and update
   `ledger.json` and `progress.md`.

## Termination
- `fixed-N`: stop after N iterations.
- `until-converged`: stop when the ledger is dry for `convergence_dry_streak` iterations.
- Always bounded by `max_iterations` and the budget cap.

## Safety invariants (enforced, not optional)
- NEVER `git push`. NEVER `git add -A` — stage only declared files via the staging wrapper.
- `target_repo` and `state_dir` are absolute and non-nested; state lives outside the target.
- Every git command is logged to `progress.md`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_doc.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/cih/SKILL.md tests/test_skill_doc.py
git commit -m "feat: interactive cih skill entry point"
```

---

## Task 23: README + final full-suite verification

**Files:**
- Create: `README.md`
- Test: (run the whole suite)

- [ ] **Step 1: Write the README**

```markdown
# Continuous Improvement Harness (CIH)

Hierarchical multi-agent harness that autonomously audits a target codebase, finds high-value
improvements, and applies them in TDD-gated iterations.

## Run (headless)
```bash
python -m cih.runner --mode fixed-N --iterations 3 \
  --target-repo /abs/path/to/target --state-dir /abs/path/to/state \
  --focus tests --focus performance
```

## Run (interactive)
Invoke the `cih` skill in Claude Code with the same parameters.

## Safety
The harness never pushes and never uses `git add -A`; `state_dir` is always outside the target
repo. See `docs/superpowers/specs/2026-06-05-cih-design.md` for the full design.
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS — all tests green across every module.

- [ ] **Step 3: Verify no forbidden git usage slipped in**

Run: `grep -rn "add -A\|add --all\|git push" cih/ | grep -v test`
Expected: no matches (staging is explicit-only; no push anywhere).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README with run instructions and safety notes"
```

---

## Self-Review Notes (author)

**Spec coverage:** §3 hierarchy → Tasks 13/14/16; §4 contracts → Tasks 11/13/20; §5 termination + ledger → Tasks 5/16; §6 flow → Tasks 14/19/21; §7 tdd_verifier (pytest + fallback) → Task 9; §8 merge queue (bounded + manifest precheck) → Task 15; §9 attempt records → Task 10; §10 state protocol (atomic/owned/transitions/resume) → Tasks 2/3/16/17; §11 safety (paths/preflight/staging/logging) → Tasks 4/6/7; §12 two entry points → Tasks 18/22; §14 self-tests → Tasks 20/21/23. All sections mapped.

**Known v1 simplifications (intentional, flagged for execution):** the merge-queue `reverify` and `integrate` in Task 15 use a callable + symbolic base SHA for unit testing; wiring real `git rebase`/full-suite re-run into `make_team_runner` is the one place execution must extend Task 19's glue (the orchestrator currently calls `team_runner_fn` but does not yet thread merge-queue integration through it end-to-end — connect `integrate()` inside `team_runner` once real worktree commits exist). This is the highest-risk integration seam; do it with a real throwaway repo and real pytest commits, not stubs.
