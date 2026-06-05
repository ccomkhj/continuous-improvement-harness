# tests/test_orchestrator.py
from pathlib import Path
from cih.config import RunConfig
from cih.orchestrator import Orchestrator, IterationResult
from cih.ledger import fingerprint
from cih.merge_queue import MergeOutcome
from cih.team import TeamResult

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
