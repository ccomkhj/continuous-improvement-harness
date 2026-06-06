# tests/test_resume.py
import subprocess
from pathlib import Path
from cih.config import RunConfig
from cih.orchestrator import Orchestrator, reconcile
from cih.state import StateHeader, write_state

def _cfg(tmp_path):
    t = tmp_path / "target"; s = tmp_path / "state"; t.mkdir(); s.mkdir()
    return RunConfig.create(mode="fixed-N", iterations=2,
                            target_repo=str(t), state_dir=str(s))

def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True).stdout.strip()

def _seed_repo(path):
    _git(["init", "-q"], path)
    _git(["config", "user.email", "t@t"], path)
    _git(["config", "user.name", "t"], path)
    (path / "f.txt").write_text("hi")
    _git(["add", "f.txt"], path)
    _git(["commit", "-q", "-m", "init"], path)
    return _git(["rev-parse", "HEAD"], path)

def _write_execution(state_dir, run_id, team_id, commits, iter_id="iter-001",
                     head_sha=None, branch=None):
    p = (Path(state_dir) / "iterations" / iter_id / "teams" / team_id /
         "execution.json")
    body = {"commits": commits}
    if branch is not None:
        body["branch"] = branch
    if head_sha is not None:
        body["head_sha"] = head_sha
    write_state(p, StateHeader(run_id, iter_id, team_id, None, "passed", "team"),
                body)

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

def test_reconcile_flags_missing_ledger_json(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_repo(Path(cfg.target_repo))
    # run.json exists but no ledger.json was written
    write_state(Path(cfg.state_dir) / "run.json",
                StateHeader("run-1", None, None, None, "done", "orchestrator"), {})
    report = reconcile(cfg, run_id="run-1")
    assert "ledger.json missing" in report["issues"]

def test_reconcile_flags_missing_branch(tmp_path):
    cfg = _cfg(tmp_path)
    base = _seed_repo(Path(cfg.target_repo))
    # run.json must exist so the path checks pass
    Orchestrator(cfg, high_planner_fn=lambda ctx: {"opportunities": [], "charters": []},
                 team_runner_fn=lambda *a, **k: []).run()
    # team artifact references a branch that was never created
    _write_execution(cfg.state_dir, "run-1", "team-99",
                     [{"red_sha": base, "green_sha": base}])
    report = reconcile(cfg, run_id="run-1")
    assert report["resumable"] is False
    assert any("cih/run-1/iter-001/team-99" in i for i in report["issues"])

def test_reconcile_flags_missing_commit(tmp_path):
    cfg = _cfg(tmp_path)
    repo = Path(cfg.target_repo)
    base = _seed_repo(repo)
    Orchestrator(cfg, high_planner_fn=lambda ctx: {"opportunities": [], "charters": []},
                 team_runner_fn=lambda *a, **k: []).run()
    # create the branch so the branch check passes, but reference a bogus red_sha
    _git(["branch", "cih/run-1/iter-001/team-01", base], repo)
    _write_execution(cfg.state_dir, "run-1", "team-01",
                     [{"red_sha": "0" * 40, "green_sha": base}], head_sha=base)
    report = reconcile(cfg, run_id="run-1")
    assert report["resumable"] is False
    assert any("commit" in i and "0000000" in i for i in report["issues"])

def test_reconcile_flags_missing_head_sha(tmp_path):
    cfg = _cfg(tmp_path)
    repo = Path(cfg.target_repo)
    base = _seed_repo(repo)
    Orchestrator(cfg, high_planner_fn=lambda ctx: {"opportunities": [], "charters": []},
                 team_runner_fn=lambda *a, **k: []).run()
    _git(["branch", "cih/run-1/iter-001/team-01", base], repo)
    # persisted head_sha does not resolve in the repo
    _write_execution(cfg.state_dir, "run-1", "team-01", [], head_sha="0" * 40)
    report = reconcile(cfg, run_id="run-1")
    assert report["resumable"] is False
    assert any("head_sha" in i and "0000000" in i for i in report["issues"])
