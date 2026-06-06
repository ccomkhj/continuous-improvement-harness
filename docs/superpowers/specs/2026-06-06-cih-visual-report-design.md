# CIH Visual Progress Report — Design Spec

**Date:** 2026-06-06
**Status:** Approved (brainstorming)
**Depends on:** the CIH harness (`cih/` package, state layout per `2026-06-05-cih-design.md` §10)

## 1. Purpose

Give a human a clear, at-a-glance **visual view of a harness run** — its status, the opportunity
ledger, the per-iteration improvement loop, per-team pipeline outcomes, and the git audit trail —
as a single self-contained HTML page that can update itself live while a run is in progress.

The harness's whole value is a transparent self-improvement loop; this turns the on-disk state
(`run.json`, `ledger.json`, `iterations/…`, `progress.md`) into something a person reads at a
glance instead of grepping JSON.

## 2. Settled decisions

| Fork | Decision |
|------|----------|
| Delivery | Live auto-refreshing, **single self-contained HTML file** (inline CSS, no JS framework, no CDN/network) |
| Content | Run header+summary, opportunity ledger, iteration timeline, per-team pipeline + git log |
| Integration | New `cih/report.py` (pure render) + `python -m cih.report` CLI + a `--report` flag on the runner that auto-emits each iteration |
| Liveness | `<meta http-equiv="refresh">` present **only while status is `in_progress`**; dropped once `done`/`failed` |

## 3. Module & boundaries (`cih/report.py`)

One module, one job: state → HTML. It must never import the orchestrator/integration layer
(the dependency goes one way: the runner wires report into the orchestrator via a callback).

- **`render_report(state_dir, *, refresh_seconds=3) -> str`** — PURE function. Reads the state
  files (read-only, tolerant of partial/missing/malformed files) and returns a complete,
  self-contained HTML document string. The testable core. Includes a meta-refresh tag iff the
  run status is `in_progress`.
- **`write_report(state_dir, out_path=None) -> Path`** — writes `render_report(state_dir)` to
  `out_path` (default `<state_dir>/report.html`); returns the path. Creates parent dir if needed.
- **CLI**: `python -m cih.report --state-dir DIR [--out PATH] [--refresh N]` — generate a snapshot
  on demand (post-hoc or mid-run). Thin `argparse` `main()` calling `write_report`.

## 4. Live updating (decoupled integration)

- `cih/runner.py` gains a `--report` flag (argparse, default off).
- `build_orchestrator(cfg, runner, ...)` accepts an optional `on_iteration_end` callback and
  passes it to `Orchestrator`. When `--report` is set, the runner injects
  `on_iteration_end = lambda: write_report(cfg.state_dir)`.
- `Orchestrator.run()` invokes `self.on_iteration_end()` (if set) **after** each iteration's state
  is persisted (after `audit.json`/`teams.json`/`iteration.md`/`ledger.json` are written) AND once
  after the loop on the success path. The callback is best-effort: a callback exception is caught
  and logged via `progress.md`, never aborts the run. (Default `None` ⇒ orchestrator behavior is
  byte-for-byte unchanged — preserves all existing tests.)
- Because `report.html` is regenerated each iteration and the page meta-refreshes every
  `refresh_seconds`, an open browser tab updates itself live until the run reaches a terminal
  status, at which point the refresh tag is omitted and the page stops reloading.

## 5. Data flow (all read-only; tolerant)

| Source | Section it feeds |
|--------|------------------|
| `run.json` (`body.config` + `body.summary`, header `status`) | Header + status badge + summary |
| `ledger.json` (`body` = `{fp: opportunity}`) | Opportunity ledger table |
| `iterations/iter-NNN/teams.json` (`body.charters`, `body.results`) | Iteration timeline cards + per-team lines |
| `iterations/iter-NNN/iteration.md` | (optional) iteration summary text |
| `iterations/iter-NNN/teams/team-NN/*` | Per-team drilldown (plan/exec/review verdicts) |
| `progress.md` | Collapsible git-activity log |

Any unreadable/missing file renders as a clearly-labeled placeholder ("— unavailable") in its
section; `render_report` never raises on bad/partial state (it is frequently called mid-run while
files are being written).

## 6. Page layout (single scrollable page, inline-styled)

1. **Header**: title (`CIH Run report · <run_id>`), color-coded status badge
   (`in_progress`/`done`/`failed`), mode, target repo, iterations run, stopped reason, budget.
2. **Opportunity ledger**: table — title · scope · value/confidence/effort/risk · state badge ·
   attempt count. State color key: `merged`=green, `open`=blue, `cooldown`=amber,
   `rejected`/`expired`=red, `in_progress`/`deferred`=grey.
3. **Iterations**: one card per `iter-NNN` — charters dispatched, merged team ids, rejected team
   ids, dry flag; each card lists its teams with pass/fail and merged/rejected disposition.
4. **Git activity**: collapsible (`<details>`) monospace block of `progress.md`.

Styling: a single inline `<style>` block; no external fonts, scripts, or stylesheets (offline-safe,
matches the no-network safety posture). Layout is plain semantic HTML (header, tables, sections,
details) so content assertions in tests are straightforward.

## 7. Error handling & safety

- `report.py` is **read-only** over `state_dir` and writes **only** `report.html` into `state_dir`
  — never the target repo, never staged, never pushed (consistent with §11 safety invariants).
- The orchestrator callback is best-effort and cannot crash a run.
- No network access, no external assets — the page works fully offline.

## 8. Testing

`render_report` is pure ⇒ tested against synthetic `state_dir` fixtures built in `tmp_path`:
- Status badge text reflects `run.json` header `status`; summary fields (mode, iterations,
  stopped reason) appear.
- Each ledger opportunity's title/fingerprint and its state appear with the right state class.
- Iteration cards show merged/rejected team ids and the dry flag from `teams.json`.
- Per-team and git-activity sections render; `progress.md` content appears in the log block.
- **meta-refresh present iff status is `in_progress`** (present for in_progress; absent for
  done/failed).
- Missing `ledger.json` / `progress.md` / a malformed JSON file ⇒ a labeled placeholder, no raise.
- `write_report` writes `<state_dir>/report.html` and returns the path.
- CLI `main(["--state-dir", DIR])` writes the file.
- `build_orchestrator(..., --report)`: after a run, `report.html` exists; across a 2-iteration run
  it is regenerated (assert it exists after the run; optionally assert content reflects the final
  iteration). Default (no `--report`) ⇒ no `report.html` and orchestrator unchanged.

## 9. Non-goals (v1)

- No live server / SSE / websockets (file + meta-refresh only).
- No JS charting/interactivity library (static, inline-CSS only).
- No historical multi-run comparison (single run per report).
- No auth/hosting — it's a local file the user opens.

## 10. Files

- Create: `cih/report.py`, `tests/test_report.py`.
- Modify: `cih/runner.py` (`--report` flag + callback wiring in `build_orchestrator`/`main`),
  `cih/orchestrator.py` (optional `on_iteration_end` callback, invoked post-persist, best-effort),
  `tests/test_orchestrator.py` and/or `tests/test_runner_cli.py` (callback + flag tests).
- README: add a short "Visual report" usage note.
