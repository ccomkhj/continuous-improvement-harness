# tests/test_orchestrator.py
from pathlib import Path
from cih.config import RunConfig
from cih.orchestrator import Orchestrator, IterationResult
from cih.ledger import fingerprint
from cih.merge_queue import MergeOutcome
from cih.state import read_state
from cih.team import TeamResult
import pytest

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

def test_until_converged_converges_when_work_is_merged(tmp_path):
    cfg = _cfg(tmp_path, mode="until-converged", iterations=None,
               convergence_dry_streak=1, max_iterations=10)
    title, scope = "stable opportunity", "scope-1"
    fp = fingerprint(title, scope)
    def high_planner(ctx):
        # always re-discovers the same high-value opportunity + a charter carrying its fp
        return {"opportunities": [{"title": title, "scope": scope, "value": 0.9,
                "confidence": 0.9, "effort": 0.1, "risk": 0.1, "rationale": "r"}],
                "charters": [{"id": "team-01", "opportunity_fp": fp}]}
    def team_runner(charters, ctx):
        return [TeamResult(team_id=c["id"], passed=True) for c in charters]
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=team_runner,
                        integrate_fn=lambda results, ctx: MergeOutcome(
                            merged=[r.team_id for r in results if r.passed]))
    summary = orch.run()
    assert summary["stopped_reason"] == "converged"
    # once merged, re-discovery is ignored (terminal) so next iteration is dry
    assert summary["iterations_run"] < cfg.max_iterations

def test_run_persists_ledger_json(tmp_path):
    cfg = _cfg(tmp_path, iterations=1)
    title, scope = "persist me", "scope-1"
    fp = fingerprint(title, scope)
    def high_planner(ctx):
        return {"opportunities": [{"title": title, "scope": scope, "value": 0.9,
                "confidence": 0.9, "effort": 0.1, "risk": 0.1, "rationale": "r"}],
                "charters": []}
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=lambda *a, **k: [])
    orch.run()
    led_path = Path(cfg.state_dir, "ledger.json")
    assert led_path.exists()
    assert fp in read_state(led_path)["body"]

def test_ledger_state_survives_resume(tmp_path):
    cfg = _cfg(tmp_path, iterations=1, cooldown_iterations=3)
    title, scope = "cooldown me", "scope-1"
    fp = fingerprint(title, scope)
    def high_planner(ctx):
        return {"opportunities": [{"title": title, "scope": scope, "value": 0.9,
                "confidence": 0.9, "effort": 0.1, "risk": 0.1, "rationale": "r"}],
                "charters": [{"id": "team-01", "opportunity_fp": fp}]}
    def team_runner(charters, ctx):
        return [TeamResult(team_id=c["id"], passed=True) for c in charters]
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=team_runner,
                        integrate_fn=lambda results, ctx: MergeOutcome(
                            rejected=[r.team_id for r in results]))
    orch.run()
    orch2 = Orchestrator(cfg, high_planner_fn=high_planner,
                         team_runner_fn=team_runner)
    assert orch2.ledger.get(fp).state == "cooldown"
    assert orch2.ledger.get(fp).attempt_count == 1

def test_budget_cap_stops_run(tmp_path):
    cfg = _cfg(tmp_path, iterations=10, budget_cap=3, max_teams_per_iteration=1)
    seen = {"n": 0, "total": 0}
    def high_planner(ctx):
        seen["n"] += 1
        return {"opportunities": [], "charters": [{"id": f"team-{seen['n']:02d}"}]}
    def team_runner(charters, ctx):
        seen["total"] += len(charters)
        return [TeamResult(team_id=c["id"], passed=True) for c in charters]
    orch = Orchestrator(cfg, high_planner_fn=high_planner, team_runner_fn=team_runner)
    summary = orch.run()
    assert summary["stopped_reason"] == "budget_exhausted"
    assert seen["total"] == 3

def test_budget_cap_truncates_within_iteration(tmp_path):
    cfg = _cfg(tmp_path, iterations=10, budget_cap=3, max_teams_per_iteration=4)
    seen = {"n": 0, "total": 0}
    def high_planner(ctx):
        seen["n"] += 1
        return {"opportunities": [],
                "charters": [{"id": f"team-{seen['n']:02d}-{j}"} for j in range(4)]}
    def team_runner(charters, ctx):
        seen["total"] += len(charters)
        return [TeamResult(team_id=c["id"], passed=True) for c in charters]
    orch = Orchestrator(cfg, high_planner_fn=high_planner, team_runner_fn=team_runner)
    summary = orch.run()
    assert seen["total"] == 3
    assert summary["stopped_reason"] == "budget_exhausted"

def test_budget_cap_none_is_unbounded(tmp_path):
    cfg = _cfg(tmp_path, iterations=2)
    def high_planner(ctx):
        return {"opportunities": [], "charters": []}
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=lambda *a, **k: [])
    summary = orch.run()
    assert summary["stopped_reason"] in ("completed",)
    assert summary["iterations_run"] == 2

def test_merged_opportunity_stays_terminal_after_resume(tmp_path):
    cfg = _cfg(tmp_path, iterations=1)
    title, scope = "merge me", "scope-1"
    fp = fingerprint(title, scope)
    def high_planner(ctx):
        return {"opportunities": [{"title": title, "scope": scope, "value": 0.9,
                "confidence": 0.9, "effort": 0.1, "risk": 0.1, "rationale": "r"}],
                "charters": [{"id": "team-01", "opportunity_fp": fp}]}
    def team_runner(charters, ctx):
        return [TeamResult(team_id=c["id"], passed=True) for c in charters]
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=team_runner,
                        integrate_fn=lambda results, ctx: MergeOutcome(
                            merged=[r.team_id for r in results]))
    orch.run()
    orch2 = Orchestrator(cfg, high_planner_fn=high_planner,
                         team_runner_fn=team_runner)
    assert orch2.ledger.get(fp).state == "merged"

def test_run_persists_failed_status_when_loop_raises(tmp_path):
    cfg = _cfg(tmp_path, iterations=2)
    def high_planner(ctx):
        raise RuntimeError("planner exploded")
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=lambda *a, **k: [])
    with pytest.raises(RuntimeError):
        orch.run()
    doc = read_state(Path(cfg.state_dir, "run.json"))
    assert doc["status"] == "failed"
    assert "planner exploded" in doc["body"]["summary"]["error"]

def test_integrate_crash_persists_failed_status(tmp_path):
    cfg = _cfg(tmp_path, iterations=1)
    title, scope = "boom", "scope-1"
    fp = fingerprint(title, scope)
    def high_planner(ctx):
        return {"opportunities": [{"title": title, "scope": scope, "value": 0.9,
                "confidence": 0.9, "effort": 0.1, "risk": 0.1, "rationale": "r"}],
                "charters": [{"id": "team-01", "opportunity_fp": fp}]}
    def team_runner(charters, ctx):
        return [TeamResult(team_id=c["id"], passed=True) for c in charters]
    def integrate_fn(results, ctx):
        raise RuntimeError("integrate exploded")
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=team_runner, integrate_fn=integrate_fn)
    with pytest.raises(RuntimeError):
        orch.run()
    doc = read_state(Path(cfg.state_dir, "run.json"))
    assert doc["status"] == "failed"

def test_run_persists_done_status_on_success(tmp_path):
    cfg = _cfg(tmp_path, iterations=1)
    def high_planner(ctx):
        return {"opportunities": [], "charters": []}
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=lambda *a, **k: [])
    orch.run()
    doc = read_state(Path(cfg.state_dir, "run.json"))
    assert doc["status"] == "done"

def test_iteration_emits_teams_json_and_iteration_md(tmp_path):
    cfg = _cfg(tmp_path, iterations=1)
    charters = [{"id": "team-01"}, {"id": "team-02"}]
    def high_planner(ctx):
        return {"opportunities": [], "charters": list(charters)}
    def team_runner(cs, ctx):
        return [TeamResult(team_id=c["id"], passed=True) for c in cs]
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=team_runner)
    orch.run()
    iter_dir = Path(cfg.state_dir, "iterations", "iter-001")
    assert (iter_dir / "teams.json").exists()
    assert (iter_dir / "iteration.md").exists()

    body = read_state(iter_dir / "teams.json")["body"]
    assert body["charters"] == charters
    assert len(body["results"]) == len(charters)
    for r in body["results"]:
        assert set(r.keys()) == {"team_id", "passed", "reason", "merged", "rejected"}
    # spec §6.3: teams.json body carries the iteration's dry flag (bool).
    # No opportunities were ever added, so the iteration is dry.
    assert isinstance(body["dry"], bool)
    assert body["dry"] is True

    md = (iter_dir / "iteration.md").read_text()
    assert md.startswith("# Iteration 1")

def test_teams_json_records_merge_disposition(tmp_path):
    cfg = _cfg(tmp_path, iterations=1)
    title, scope = "merge me", "scope-1"
    fp = fingerprint(title, scope)
    def high_planner(ctx):
        return {"opportunities": [{"title": title, "scope": scope, "value": 0.9,
                "confidence": 0.9, "effort": 0.1, "risk": 0.1, "rationale": "r"}],
                "charters": [{"id": "team-01", "opportunity_fp": fp}]}
    def team_runner(cs, ctx):
        return [TeamResult(team_id=c["id"], passed=True) for c in cs]
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=team_runner,
                        integrate_fn=lambda results, ctx: MergeOutcome(
                            merged=[r.team_id for r in results]))
    orch.run()
    iter_dir = Path(cfg.state_dir, "iterations", "iter-001")
    body = read_state(iter_dir / "teams.json")["body"]
    by_id = {r["team_id"]: r for r in body["results"]}
    assert by_id["team-01"]["merged"] is True
    assert by_id["team-01"]["rejected"] is False
    md = (iter_dir / "iteration.md").read_text()
    assert "team-01" in md.split("merged:", 1)[1].split("\n", 1)[0]


def test_teams_json_records_not_dry_when_opportunity_open(tmp_path):
    # An ingested opportunity above threshold that is never merged/rejected
    # stays open, so the iteration is NOT dry (spec §6.3 dry flag in body).
    cfg = _cfg(tmp_path, iterations=1)
    def high_planner(ctx):
        return {"opportunities": [{"title": "t", "scope": "s", "value": 0.9,
                "confidence": 0.9, "effort": 0.1, "risk": 0.1, "rationale": "r"}],
                "charters": []}
    orch = Orchestrator(cfg, high_planner_fn=high_planner,
                        team_runner_fn=lambda *a, **k: [])
    orch.run()
    iter_dir = Path(cfg.state_dir, "iterations", "iter-001")
    body = read_state(iter_dir / "teams.json")["body"]
    assert body["dry"] is False


def test_on_iteration_end_called_each_iteration(tmp_path):
    cfg = _cfg(tmp_path, iterations=3)
    calls = {"n": 0}
    orch = Orchestrator(cfg,
                        high_planner_fn=lambda ctx: {"opportunities": [], "charters": []},
                        team_runner_fn=lambda *a, **k: [],
                        on_iteration_end=lambda: calls.__setitem__("n", calls["n"] + 1))
    orch.run()
    # N per-iteration fires (after each in_progress persist) + 1 final fire
    # after the done persist, so the report renders against the terminal state.
    assert calls["n"] == 4


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
