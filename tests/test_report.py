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
