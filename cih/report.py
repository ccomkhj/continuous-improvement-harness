import argparse
import html as _html
import json
import sys
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

def _render_ledger(state_dir: Path) -> str:
    doc = _load_json(Path(state_dir) / "ledger.json")
    body = doc.get("body") if isinstance(doc, dict) else None
    if not body:
        return ("<section><h2>Opportunity ledger</h2>"
                "<p class='muted'>ledger.json unavailable</p></section>")
    rows = []
    for opp in body.values():
        if not isinstance(opp, dict):
            continue
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
    if not isinstance(results, list):
        results = []
    merged = [r.get("team_id") for r in results if isinstance(r, dict) and r.get("merged")]
    rejected = [r.get("team_id") for r in results if isinstance(r, dict) and r.get("rejected")]
    dry = body.get("dry")
    team_lines = "".join(
        "<li>"
        f"{_esc(r.get('team_id'))} "
        f"<span class='badge s-{'merged' if r.get('merged') else ('rejected' if r.get('rejected') else 'open')}'>"
        f"{'merged' if r.get('merged') else ('rejected' if r.get('rejected') else ('passed' if r.get('passed') else 'failed'))}</span> "
        f"<span class='muted'>{_esc(r.get('reason', ''))}</span></li>"
        for r in results if isinstance(r, dict)
    )
    return (
        f"<div class='iter'><b>Iteration {_esc(num)}</b> "
        f"<span class='muted'>charters {len(body.get('charters', []))} &middot; "
        f"merged {_esc(merged)} &middot; rejected {_esc(rejected)} &middot; dry {_esc(dry)}</span>"
        f"<ul>{team_lines}</ul></div>"
    )

def _render_iterations(state_dir: Path) -> str:
    dirs = _iteration_dirs(state_dir)
    if not dirs:
        return "<section><h2>Iterations</h2><p class='muted'>no iterations yet</p></section>"
    cards = "".join(_render_one_iteration(d) for d in dirs)
    return f"<section><h2>Iterations</h2>{cards}</section>"

def _render_git_log(state_dir: Path) -> str:
    text = _read_text(Path(state_dir) / "progress.md")
    if not text:
        return ("<section><h2>Git activity</h2>"
                "<p class='muted'>progress.md unavailable</p></section>")
    return ("<section><h2>Git activity</h2>"
            f"<details open><pre>{_esc(text)}</pre></details></section>")

def render_report(state_dir, *, refresh_seconds: int = 3) -> str:
    state_dir = Path(state_dir)
    header_html, status = _render_header(state_dir)
    refresh = (f"<meta http-equiv=\"refresh\" content=\"{int(refresh_seconds)}\">"
               if status == "in_progress" else "")
    body_html = (header_html + _render_ledger(state_dir)
                 + _render_iterations(state_dir) + _render_git_log(state_dir))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"{refresh}<title>CIH Run report</title><style>{_STYLE}</style></head>"
        f"<body><div class='wrap'>{body_html}</div></body></html>"
    )

def write_report(state_dir, out_path=None, refresh_seconds: int = 3) -> Path:
    state_dir = Path(state_dir)
    out = Path(out_path) if out_path is not None else state_dir / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(state_dir, refresh_seconds=refresh_seconds))
    return out

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cih.report",
                                description="Render a CIH run state_dir to HTML")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--refresh", type=int, default=3)
    ns = p.parse_args(argv if argv is not None else sys.argv[1:])
    out = write_report(ns.state_dir, out_path=ns.out, refresh_seconds=ns.refresh)
    print(f"wrote {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
