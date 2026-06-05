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
