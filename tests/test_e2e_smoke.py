# tests/test_e2e_smoke.py
"""End-to-end fixed-N smoke run through the REAL integration layer.

This wires a real throwaway git repo to build_integration (worktree-backed
team_runner + merge-queue integrate_fn) and the Orchestrator, driven entirely
by a StubRunner. Each iteration emits ONE charter carrying a stable
opportunity_fp; the team passes plan-review/exec-review with an empty
`{"commits": []}` executor result and an injected green TDD verifier.

Simplification (documented, per Task C): the executor stub produces no real
file changes, so the merge queue has nothing to merge and the run still
completes and persists per-iteration + per-team state. This proves the
orchestrator -> team_runner -> worktree -> integrate assembly holds together
through the real integration code path. We deliberately do NOT weaken any
other test to make this pass.
"""

import subprocess
from pathlib import Path

from cih.agents import StubRunner, invoke
from cih.config import RunConfig
from cih.integration import build_integration
from cih.ledger import fingerprint
from cih.orchestrator import Orchestrator
from cih.roles import load_contracts
from cih.tdd_verifier import TddVerdict


def _seed_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=str(path), check=True)
    (path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(path), check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(path), capture_output=True, text=True
    ).stdout.strip()


def test_full_fixed_n_run_through_real_integration(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    state = tmp_path / "state"
    state.mkdir()
    cfg = RunConfig.create(
        mode="fixed-N", iterations=2, target_repo=str(repo), state_dir=str(state)
    )

    opp_fp = fingerprint("improve thing", "module")
    charter = {
        "id": "team-01",
        "goal": "g",
        "opportunity_fp": opp_fp,
        "impact_manifest": {"intended_files": ["a.py"]},
    }
    runner = StubRunner(
        responses={
            "high-planner": {"opportunities": [], "charters": [charter]},
            "planner": {"tasks": ["t1"]},
            "plan-reviewer": {"approved": True, "feedback": ""},
            "executor": {"commits": []},
            "execution-reviewer": {"approved": True, "reasons": ["ok"]},
        }
    )
    contracts = load_contracts()

    team_runner, integrate_fn = build_integration(
        contracts=contracts,
        runner=runner,
        verifier=lambda **k: TddVerdict(eligible=True, passed=True),
        repo=repo,
        worktrees_root=tmp_path / "wts",
        run_id="run-1",
        base_sha=base,
        state_dir=state,
        plan_review_retries=1,
        exec_review_retries=1,
        attempt_cap=4,
        integration_retries=0,
    )

    def high_planner(ctx):
        return invoke(runner, contracts["high-planner"], ctx)

    orch = Orchestrator(
        cfg,
        high_planner_fn=high_planner,
        team_runner_fn=team_runner,
        integrate_fn=integrate_fn,
        run_id="run-1",
    )
    summary = orch.run()

    assert summary["iterations_run"] == 2
    assert (state / "run.json").exists()
    assert (state / "iterations" / "iter-001" / "audit.json").exists()
    teamdir = state / "iterations" / "iter-001" / "teams" / "team-01"
    for fname in ("plan.json", "execution.json", "exec_review.json", "attempts.json"):
        assert (teamdir / fname).exists(), fname
