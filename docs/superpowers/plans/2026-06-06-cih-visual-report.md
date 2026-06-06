# CIH Visual Progress Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render a CIH harness run's on-disk state into a single self-contained, live-auto-refreshing HTML progress page.

**Architecture:** A new pure module `cih/report.py` composes section helpers (`_render_header`, `_render_ledger`, `_render_iterations`, `_render_git_log`) into one HTML string via `render_report(state_dir)`; `write_report` persists it to `<state_dir>/report.html`; a `python -m cih.report` CLI generates snapshots; and a `--report` runner flag injects a best-effort `on_iteration_end` callback so the orchestrator regenerates the file each iteration. No JS framework, no CDN, inline CSS — offline-safe. The page meta-refreshes only while status is `in_progress`.

**Tech Stack:** Python 3.11+ stdlib only (`json`, `html`, `pathlib`, `argparse`), pytest.

---

## State shapes this consumes (read these from the existing code first)

All state files are written by `cih/state.py`'s `write_state`, producing a doc with top-level header fields (`schema_version, run_id, iteration_id, team_id, attempt_id, status, owner, created_at, updated_at`) and the payload under `body`. Key files (under an absolute `state_dir`):
- `run.json` — header `status` ∈ {`in_progress`,`done`,`failed`}. `body` is the config dict while in_progress; on done/failed it is `{"config": <cfg>, "summary": {...}}`. So: status from header; `summary = body.get("summary")`; `config = body.get("config", body)`.
- `ledger.json` — `body` = `{fingerprint: {fp, title, scope, value, confidence, effort, risk, rationale, state, attempt_count, cooldown_until}}`.
- `iterations/iter-NNN/teams.json` — `body` = `{"charters": [...], "results": [{"team_id", "passed", "reason", "merged", "rejected"}]}`.
- `iterations/iter-NNN/iteration.md` — plain markdown text (optional).
- `progress.md` — plain text, timestamped git-command lines.

Read `cih/state.py` (`read_state`), `cih/orchestrator.py` (`run()` persistence block, `_persist_run`, `_persist_ledger`, `__init__`), `cih/runner.py` (`parse_args`, `build_config`, `build_orchestrator`, `main`), and `cih/progress.py` (`append_progress`) before starting.

## File structure

| File | Responsibility |
|------|----------------|
| `cih/report.py` | Pure state→HTML rendering, `write_report`, CLI `main` |
| `cih/orchestrator.py` (modify) | Optional `on_iteration_end` callback, invoked best-effort post-persist |
| `cih/runner.py` (modify) | `--report` flag; wire callback through `build_orchestrator`/`main` |
| `tests/test_report.py` | Pure-render + write + CLI tests over synthetic `state_dir` fixtures |
| `tests/test_orchestrator.py` (modify) | callback invocation tests |
| `tests/test_runner_cli.py` (modify) | `--report` flag wiring test |
| `README.md` (modify) | "Visual report" usage note |

All work on branch `feat/cih-implementation`. Constraints for every commit: NEVER `git add -A`/wildcards (stage only listed files); NEVER push; no "Co-Authored-By: Claude" trailer. Run tests via the project venv: `source .venv/bin/activate`. The suite currently has 131 passing tests.

---

## Task 1: `render_report` skeleton + header section + meta-refresh

**Files:**
- Create: `cih/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
import json
from pathlib import Path
from cih.report import render_report

def _write(path: Path, status: str, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "run_id": "run-1", "iteration_id": None,
           "team_id": None, "attempt_id": None, "status": status,
           "owner": "orchestrator", "created_at": "t", "updated_at": "t", "body": body}
    path.write_text(json.dumps(doc))

def test_header_shows_status_and_summary(tmp_path):
    _write(tmp_path / "run.json", "done",
           {"config": {"mode": "fixed-N", "target_repo": "/tgt"},
            "summary": {"iterations_run": 2, "stopped_reason": "completed"}})
    html = render_report(tmp_path)
    assert "<!doctype html>" in html.lower()
    assert "run-1" in html
    assert "done" in html
    assert "fixed-N" in html
    assert "/tgt" in html
    assert "completed" in html

def test_meta_refresh_only_when_in_progress(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    assert "http-equiv=\"refresh\"" in render_report(tmp_path)
    _write(tmp_path / "run.json", "done",
           {"config": {"mode": "fixed-N", "target_repo": "/t"}, "summary": {}})
    assert "http-equiv=\"refresh\"" not in render_report(tmp_path)

def test_missing_run_json_does_not_raise(tmp_path):
    html = render_report(tmp_path)  # empty state_dir
    assert "unavailable" in html.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cih.report'`

- [ ] **Step 3: Write minimal implementation**

```python
# cih/report.py
import html as _html
import json
from pathlib import Path
from typing import Optional

def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

def _read_text(path: Path) -> Optional[str]:
    try:
        return Path(path).read_text()
    except (FileNotFoundError, OSError):
        return None

def _esc(value) -> str:
    return _html.escape(str(value))

_STYLE = """
body{font-family:system-ui,Arial,sans-serif;margin:0;background:#0f1419;color:#e6e6e6}
.wrap{max-width:960px;margin:0 auto;padding:24px}
h1{font-size:20px;margin:0 0 4px}
section{background:#1a212b;border:1px solid #2a323d;border-radius:8px;padding:16px;margin:16px 0}
h2{font-size:15px;margin:0 0 12px;color:#9fb3c8}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #2a323d}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600}
.s-in_progress,.s-open{background:#1d3a5f;color:#7fb6ff}
.s-done,.s-merged{background:#1d5f3a;color:#7fffb6}
.s-failed,.s-rejected,.s-expired{background:#5f1d1d;color:#ff9f9f}
.s-cooldown{background:#5f4a1d;color:#ffd27f}
.s-deferred,.s-unknown{background:#33373d;color:#aaa}
.muted{color:#8a94a0}
pre{white-space:pre-wrap;font-size:12px;background:#11161d;padding:10px;border-radius:6px;margin:0}
"""

def _render_header(state_dir: Path) -> tuple[str, str]:
    doc = _load_json(Path(state_dir) / "run.json")
    if doc is None:
        return ("<section><h1>CIH Run report</h1>"
                "<p class='muted'>run.json unavailable</p></section>", "unknown")
    status = doc.get("status", "unknown")
    body = doc.get("body", {})
    summary = body.get("summary", {}) if isinstance(body, dict) else {}
    config = body.get("config", body) if isinstance(body, dict) else {}
    run_id = doc.get("run_id", "?")
    rows = [
        f"mode: {_esc(config.get('mode', '?'))}",
        f"target: {_esc(config.get('target_repo', '?'))}",
        f"iterations run: {_esc(summary.get('iterations_run', '—'))}",
        f"stopped: {_esc(summary.get('stopped_reason', '—'))}",
        f"budget: {_esc(config.get('budget_cap', '—'))}",
    ]
    html_str = (
        f"<section><h1>CIH Run report · {_esc(run_id)}</h1>"
        f"<span class='badge s-{_esc(status)}'>{_esc(status)}</span>"
        f"<p class='muted'>{' &middot; '.join(rows)}</p></section>"
    )
    return html_str, status

def render_report(state_dir, *, refresh_seconds: int = 3) -> str:
    state_dir = Path(state_dir)
    header_html, status = _render_header(state_dir)
    refresh = (f"<meta http-equiv=\"refresh\" content=\"{int(refresh_seconds)}\">"
               if status == "in_progress" else "")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"{refresh}<title>CIH Run report</title><style>{_STYLE}</style></head>"
        f"<body><div class='wrap'>{header_html}</div></body></html>"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/report.py tests/test_report.py
git commit -m "feat: report header section with status badge and conditional meta-refresh"
```

---

## Task 2: Opportunity ledger section

**Files:**
- Modify: `cih/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_report.py
from cih.report import render_report   # already imported; ensure present

def test_ledger_rows_render_with_state_classes(tmp_path):
    # minimal run.json so header renders
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    ledger_body = {
        "fp1": {"fp": "fp1", "title": "Improve coverage", "scope": "tests/",
                "value": 0.9, "confidence": 0.8, "effort": 0.2, "risk": 0.1,
                "rationale": "r", "state": "merged", "attempt_count": 1,
                "cooldown_until": None},
        "fp2": {"fp": "fp2", "title": "Refactor io", "scope": "io.py",
                "value": 0.6, "confidence": 0.5, "effort": 0.5, "risk": 0.4,
                "rationale": "r", "state": "cooldown", "attempt_count": 2,
                "cooldown_until": 5},
    }
    _write(tmp_path / "ledger.json", "in_progress", ledger_body)
    html = render_report(tmp_path)
    assert "Improve coverage" in html
    assert "Refactor io" in html
    assert "s-merged" in html
    assert "s-cooldown" in html

def test_missing_ledger_renders_placeholder(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    html = render_report(tmp_path)
    assert "Opportunity ledger" in html
    assert "unavailable" in html.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -k ledger -v`
Expected: FAIL — `assert 'Improve coverage' in html` fails (no ledger section yet)

- [ ] **Step 3: Write minimal implementation**

Add to `cih/report.py`:

```python
def _render_ledger(state_dir: Path) -> str:
    doc = _load_json(Path(state_dir) / "ledger.json")
    body = doc.get("body") if isinstance(doc, dict) else None
    if not body:
        return ("<section><h2>Opportunity ledger</h2>"
                "<p class='muted'>ledger.json unavailable</p></section>")
    rows = []
    for opp in body.values():
        state = opp.get("state", "unknown")
        rows.append(
            "<tr>"
            f"<td>{_esc(opp.get('title', '?'))}</td>"
            f"<td class='muted'>{_esc(opp.get('scope', ''))}</td>"
            f"<td>{_esc(opp.get('value', '—'))}</td>"
            f"<td>{_esc(opp.get('confidence', '—'))}</td>"
            f"<td>{_esc(opp.get('effort', '—'))}</td>"
            f"<td>{_esc(opp.get('risk', '—'))}</td>"
            f"<td><span class='badge s-{_esc(state)}'>{_esc(state)}</span></td>"
            f"<td>{_esc(opp.get('attempt_count', 0))}</td>"
            "</tr>"
        )
    return (
        "<section><h2>Opportunity ledger</h2><table>"
        "<tr><th>title</th><th>scope</th><th>v</th><th>c</th><th>e</th>"
        "<th>r</th><th>state</th><th>attempts</th></tr>"
        + "".join(rows) + "</table></section>"
    )
```

And insert it into the body assembly in `render_report` (after `header_html`):

```python
    body_html = header_html + _render_ledger(state_dir)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"{refresh}<title>CIH Run report</title><style>{_STYLE}</style></head>"
        f"<body><div class='wrap'>{body_html}</div></body></html>"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/report.py tests/test_report.py
git commit -m "feat: report opportunity-ledger section"
```

---

## Task 3: Iteration timeline + per-team lines

**Files:**
- Modify: `cih/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_report.py
def test_iteration_cards_render_team_disposition(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    teams_body = {
        "charters": [{"id": "team-01"}, {"id": "team-02"}],
        "results": [
            {"team_id": "team-01", "passed": True, "reason": "passed",
             "merged": True, "rejected": False},
            {"team_id": "team-02", "passed": False, "reason": "exec rejected",
             "merged": False, "rejected": True},
        ],
    }
    _write(tmp_path / "iterations" / "iter-001" / "teams.json", "open", teams_body)
    html = render_report(tmp_path)
    assert "Iteration 1" in html or "iter-001" in html
    assert "team-01" in html
    assert "team-02" in html
    assert "s-merged" in html      # team-01 disposition
    assert "s-rejected" in html    # team-02 disposition

def test_missing_iterations_render_placeholder(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    html = render_report(tmp_path)
    assert "Iterations" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -k iteration -v`
Expected: FAIL — `team-01` not in html (no iterations section yet)

- [ ] **Step 3: Write minimal implementation**

Add to `cih/report.py`:

```python
def _iteration_dirs(state_dir: Path):
    iters = Path(state_dir) / "iterations"
    if not iters.is_dir():
        return []
    return sorted(d for d in iters.iterdir() if d.is_dir() and d.name.startswith("iter-"))

def _render_one_iteration(d: Path) -> str:
    doc = _load_json(d / "teams.json")
    body = doc.get("body") if isinstance(doc, dict) else None
    num = d.name.replace("iter-", "").lstrip("0") or "0"
    if not body:
        return (f"<div class='iter'><b>Iteration {_esc(num)}</b> "
                "<span class='muted'>(teams.json unavailable)</span></div>")
    results = body.get("results", [])
    merged = [r["team_id"] for r in results if r.get("merged")]
    rejected = [r["team_id"] for r in results if r.get("rejected")]
    team_lines = "".join(
        "<li>"
        f"{_esc(r.get('team_id'))} "
        f"<span class='badge s-{'merged' if r.get('merged') else ('rejected' if r.get('rejected') else 'open')}'>"
        f"{'merged' if r.get('merged') else ('rejected' if r.get('rejected') else ('passed' if r.get('passed') else 'failed'))}</span> "
        f"<span class='muted'>{_esc(r.get('reason', ''))}</span></li>"
        for r in results
    )
    return (
        f"<div class='iter'><b>Iteration {_esc(num)}</b> "
        f"<span class='muted'>charters {len(body.get('charters', []))} &middot; "
        f"merged {_esc(merged)} &middot; rejected {_esc(rejected)}</span>"
        f"<ul>{team_lines}</ul></div>"
    )

def _render_iterations(state_dir: Path) -> str:
    dirs = _iteration_dirs(state_dir)
    if not dirs:
        return "<section><h2>Iterations</h2><p class='muted'>no iterations yet</p></section>"
    cards = "".join(_render_one_iteration(d) for d in dirs)
    return f"<section><h2>Iterations</h2>{cards}</section>"
```

Update the body assembly in `render_report`:

```python
    body_html = header_html + _render_ledger(state_dir) + _render_iterations(state_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/report.py tests/test_report.py
git commit -m "feat: report iteration timeline with per-team disposition"
```

---

## Task 4: Git-activity log section (`progress.md`)

**Files:**
- Modify: `cih/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_report.py
def test_git_activity_renders_progress_md(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    (tmp_path / "progress.md").write_text(
        "2026-06-06T00:00:00+00:00 git -C /t worktree add -b cih/run-1/iter-001/team-01 ...\n")
    html = render_report(tmp_path)
    assert "Git activity" in html
    assert "worktree add" in html

def test_git_activity_escapes_html(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    (tmp_path / "progress.md").write_text("git log <script>alert(1)</script>\n")
    html = render_report(tmp_path)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -k git_activity -v`
Expected: FAIL — "Git activity" not in html

- [ ] **Step 3: Write minimal implementation**

Add to `cih/report.py`:

```python
def _render_git_log(state_dir: Path) -> str:
    text = _read_text(Path(state_dir) / "progress.md")
    if not text:
        return ("<section><h2>Git activity</h2>"
                "<p class='muted'>progress.md unavailable</p></section>")
    return ("<section><h2>Git activity</h2>"
            f"<details open><pre>{_esc(text)}</pre></details></section>")
```

Update the body assembly in `render_report`:

```python
    body_html = (header_html + _render_ledger(state_dir)
                 + _render_iterations(state_dir) + _render_git_log(state_dir))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/report.py tests/test_report.py
git commit -m "feat: report git-activity log section (html-escaped)"
```

---

## Task 5: `write_report` + `python -m cih.report` CLI

**Files:**
- Modify: `cih/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_report.py
from cih.report import write_report, main

def test_write_report_writes_html_into_state_dir(tmp_path):
    _write(tmp_path / "run.json", "done",
           {"config": {"mode": "fixed-N", "target_repo": "/t"}, "summary": {}})
    out = write_report(tmp_path)
    assert out == tmp_path / "report.html"
    assert out.exists()
    assert "<!doctype html>" in out.read_text().lower()

def test_write_report_custom_out(tmp_path):
    _write(tmp_path / "run.json", "done",
           {"config": {"mode": "fixed-N", "target_repo": "/t"}, "summary": {}})
    custom = tmp_path / "sub" / "r.html"
    out = write_report(tmp_path, out_path=custom)
    assert out == custom and custom.exists()

def test_cli_main_writes_report(tmp_path):
    _write(tmp_path / "run.json", "done",
           {"config": {"mode": "fixed-N", "target_repo": "/t"}, "summary": {}})
    rc = main(["--state-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "report.html").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -k "write_report or cli_main" -v`
Expected: FAIL — `ImportError: cannot import name 'write_report'`

- [ ] **Step 3: Write minimal implementation**

Add to `cih/report.py`:

```python
import argparse
import sys

def write_report(state_dir, out_path=None) -> Path:
    state_dir = Path(state_dir)
    out = Path(out_path) if out_path is not None else state_dir / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(state_dir))
    return out

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cih.report",
                                description="Render a CIH run state_dir to HTML")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--refresh", type=int, default=3)
    ns = p.parse_args(argv if argv is not None else sys.argv[1:])
    out = write_report(ns.state_dir, out_path=ns.out)
    print(f"wrote {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

(Move the `import argparse`/`import sys` lines to the top of the file with the other imports per project style.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add cih/report.py tests/test_report.py
git commit -m "feat: write_report and python -m cih.report CLI"
```

---

## Task 6: Orchestrator `on_iteration_end` callback (best-effort, post-persist)

**Files:**
- Modify: `cih/orchestrator.py`
- Test: `tests/test_orchestrator.py`

First READ `cih/orchestrator.py`: confirm `Orchestrator.__init__` signature and the per-iteration block where `audit.json`/`teams.json`/`iteration.md`/`ledger.json` are written, and the success-path final persist. Also confirm `cih/progress.py` `append_progress(state_dir, line)` exists (used to log a callback failure).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_orchestrator.py  (uses the existing _cfg helper in that file)
def test_on_iteration_end_called_each_iteration(tmp_path):
    cfg = _cfg(tmp_path, iterations=3)
    calls = {"n": 0}
    orch = Orchestrator(cfg,
                        high_planner_fn=lambda ctx: {"opportunities": [], "charters": []},
                        team_runner_fn=lambda *a, **k: [],
                        on_iteration_end=lambda: calls.__setitem__("n", calls["n"] + 1))
    orch.run()
    assert calls["n"] == 3

def test_on_iteration_end_failure_does_not_abort_run(tmp_path):
    cfg = _cfg(tmp_path, iterations=2)
    def boom():
        raise RuntimeError("report boom")
    orch = Orchestrator(cfg,
                        high_planner_fn=lambda ctx: {"opportunities": [], "charters": []},
                        team_runner_fn=lambda *a, **k: [],
                        on_iteration_end=boom)
    summary = orch.run()  # must NOT raise
    assert summary["iterations_run"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py -k on_iteration_end -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'on_iteration_end'`

- [ ] **Step 3: Write minimal implementation**

In `cih/orchestrator.py`:
1. Add `on_iteration_end=None` to `Orchestrator.__init__` parameters and store `self.on_iteration_end = on_iteration_end`.
2. Add a private helper:

```python
    def _fire_iteration_end(self) -> None:
        if self.on_iteration_end is None:
            return
        try:
            self.on_iteration_end()
        except Exception as e:  # best-effort: never abort the run
            from cih.progress import append_progress
            append_progress(self.state_dir, f"on_iteration_end callback failed: {e}")
```

3. Call `self._fire_iteration_end()` at the END of each iteration's body (after `self._persist_ledger("in_progress")` / the per-iteration persistence), and once more on the success path after the final `_persist_run("done", ...)` / `_persist_ledger("done")`. Do NOT call it in the `except`/crash branch.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (all orchestrator tests, including the 2 new)

- [ ] **Step 5: Commit**

```bash
git add cih/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator on_iteration_end callback (best-effort, post-persist)"
```

---

## Task 7: Runner `--report` flag wiring

**Files:**
- Modify: `cih/runner.py`
- Test: `tests/test_runner_cli.py`

First READ `cih/runner.py`: `parse_args`, `build_config`, `build_orchestrator(cfg, runner, run_id=...)`, and `main`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_runner_cli.py
import subprocess
from pathlib import Path
from cih.runner import parse_args, build_orchestrator
from cih.agents import StubRunner

def _seed_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)

def test_parse_args_report_flag(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "fixed-N", "--iterations", "1",
                     "--target-repo", str(t), "--state-dir", str(s), "--report"])
    assert ns.report is True

def test_build_orchestrator_report_emits_html(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); _seed_repo(repo)
    state = tmp_path / "state"; state.mkdir()
    ns = parse_args(["--mode", "fixed-N", "--iterations", "1",
                     "--target-repo", str(repo), "--state-dir", str(state), "--report"])
    from cih.runner import build_config
    cfg = build_config(ns)
    stub = StubRunner(responses={"high-planner": {"opportunities": [], "charters": []}})
    orch = build_orchestrator(cfg, stub, report=ns.report)
    orch.run()
    assert (state / "report.html").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_runner_cli.py -k report -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'report'` (then, after flag added, `report.html` missing until wiring done)

- [ ] **Step 3: Write minimal implementation**

In `cih/runner.py`:
1. In `parse_args`, add: `p.add_argument("--report", action="store_true", help="write/update report.html each iteration")`.
2. Change `build_orchestrator(cfg, runner, run_id="run-1")` to `build_orchestrator(cfg, runner, run_id="run-1", report=False)`. Inside, after building the orchestrator's other callables, construct the callback when `report` is set and pass it to `Orchestrator(...)`:

```python
    from cih.report import write_report
    on_iter = (lambda: write_report(cfg.state_dir)) if report else None
    return Orchestrator(cfg, high_planner_fn=high_planner_fn,
                        team_runner_fn=team_runner, integrate_fn=integrate_fn,
                        run_id=run_id, on_iteration_end=on_iter)
```

3. In `main`, pass `report=ns.report` to `build_orchestrator`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_runner_cli.py -v`
Expected: PASS (existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add cih/runner.py tests/test_runner_cli.py
git commit -m "feat: --report flag wires per-iteration report.html emission"
```

---

## Task 8: README note + full-suite verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the usage note**

Append to `README.md` a section:

```markdown
## Visual report

Generate a self-contained HTML view of a run's state:

​```bash
python -m cih.report --state-dir /abs/path/to/state   # writes <state_dir>/report.html
​```

Or pass `--report` to the runner to (re)write `report.html` after every iteration; open it in a
browser — it auto-refreshes while the run is `in_progress` and stops once it's `done`/`failed`.
The page is fully self-contained (inline CSS, no network) and read-only over the state directory.
```

- [ ] **Step 2: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS — all prior tests plus the new report/orchestrator/runner tests green.

- [ ] **Step 3: Verify the report renders against a real run's state**

Run:
```bash
python - <<'PY'
import tempfile, json, pathlib
from cih.report import render_report
d = pathlib.Path(tempfile.mkdtemp())
(d/"run.json").write_text(json.dumps({"status":"in_progress","run_id":"run-1",
  "body":{"mode":"fixed-N","target_repo":"/t"}}))
html = render_report(d)
assert "<!doctype html>" in html.lower() and "run-1" in html
print("render_report OK")
PY
```
Expected: prints `render_report OK`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: visual report usage note"
```

---

## Self-Review Notes (author)

**Spec coverage:** §3 module (render_report/write_report/CLI) → Tasks 1–5; §4 live updating (callback + flag + meta-refresh) → Tasks 6–7 + Task 1 refresh logic; §5 data flow (run/ledger/teams/progress, tolerant) → Tasks 1–4 with placeholder tests; §6 layout (4 sections + state colors) → Tasks 1–4 + `_STYLE`; §7 safety (read-only, writes only report.html, best-effort callback) → Task 5 (`write_report` only target) + Task 6 (best-effort); §8 testing (purity, meta-refresh iff in_progress, placeholders, CLI, flag wiring) → all tasks' tests; §9 non-goals respected (no server/JS/charts). All sections mapped.

**Type/consistency:** `render_report(state_dir, *, refresh_seconds=3)`, `write_report(state_dir, out_path=None) -> Path`, `main(argv=None) -> int`, helper names `_render_header/_render_ledger/_render_iterations/_render_git_log`, `build_orchestrator(..., report=False)`, `Orchestrator(..., on_iteration_end=None)` — consistent across tasks. The body-assembly line in `render_report` is updated in Tasks 2/3/4 (each shows the full updated line) — implementers editing in order get the final 4-section form.

**Note:** Task 6 references the existing `_cfg` helper and success-path persist calls in `orchestrator.py`; the implementer must read the current code to place `_fire_iteration_end()` exactly (the plan specifies "after per-iteration persistence" and "after the final done-persist, not in the crash branch").
