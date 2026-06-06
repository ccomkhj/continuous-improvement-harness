import json
from pathlib import Path
from cih.report import render_report
from cih.report import write_report, main

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

def test_iteration_card_shows_dry_flag(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    teams_body = {
        "charters": [{"id": "team-01"}],
        "results": [
            {"team_id": "team-01", "passed": True, "reason": "passed",
             "merged": True, "rejected": False},
        ],
        "dry": True,
    }
    _write(tmp_path / "iterations" / "iter-001" / "teams.json", "open", teams_body)
    html = render_report(tmp_path)
    assert "dry" in html
    assert "True" in html

def test_iteration_card_tolerates_missing_dry(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    teams_body = {
        "charters": [{"id": "team-01"}],
        "results": [
            {"team_id": "team-01", "passed": True, "reason": "passed",
             "merged": True, "rejected": False},
        ],
    }
    _write(tmp_path / "iterations" / "iter-001" / "teams.json", "open", teams_body)
    html = render_report(tmp_path)  # must not raise
    assert "Iteration 1" in html or "iter-001" in html

def test_missing_iterations_render_placeholder(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    html = render_report(tmp_path)
    assert "Iterations" in html

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

def test_iteration_tolerates_malformed_result_row(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    teams_body = {
        "charters": [{"id": "team-01"}],
        "results": [
            {"merged": True},          # missing team_id
            "not-a-dict",              # non-dict entry
            {"team_id": "team-02", "rejected": True},
        ],
    }
    _write(tmp_path / "iterations" / "iter-001" / "teams.json", "open", teams_body)
    html = render_report(tmp_path)  # must not raise
    assert "Iteration 1" in html or "iter-001" in html
    assert "team-02" in html

def test_write_report_forwards_refresh_seconds(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    out = write_report(tmp_path, refresh_seconds=7)
    assert 'content="7"' in out.read_text()

def test_ledger_tolerates_non_dict_value(tmp_path):
    _write(tmp_path / "run.json", "in_progress", {"mode": "fixed-N", "target_repo": "/t"})
    _write(tmp_path / "ledger.json", "in_progress",
           {"fp1": "not-a-dict",
            "fp2": {"title": "Good one", "state": "open"}})
    html = render_report(tmp_path)  # must not raise
    assert "Good one" in html
