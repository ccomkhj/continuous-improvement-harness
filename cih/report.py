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
