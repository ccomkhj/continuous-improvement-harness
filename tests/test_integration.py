# tests/test_integration.py
import re
import subprocess
from pathlib import Path

from cih.agents import StubRunner
from cih.integration import build_integration
from cih.roles import load_contracts
from cih.tdd_verifier import TddVerdict


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True).stdout.strip()


def _seed_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], path)
    _git(["config", "user.email", "t@t"], path)
    _git(["config", "user.name", "t"], path)
    (path / "f.txt").write_text("hi")
    _git(["add", "f.txt"], path)
    _git(["commit", "-q", "-m", "init"], path)
    return _git(["rev-parse", "HEAD"], path)


def _green_verifier(**kwargs):
    return TddVerdict(eligible=True, passed=True)


def _passing_runner(approved=True):
    return StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": []},
        "execution-reviewer": {"approved": approved,
                               "reasons": [] if approved else ["no"]},
    })


def _charter(team_id, intended_files=("a.txt",)):
    return {"id": team_id, "goal": "x", "opportunity_fp": "fp-" + team_id,
            "impact_manifest": {"intended_files": list(intended_files)}}


def _commit_in_worktree(wt_path, fname, content, msg):
    p = Path(wt_path) / fname
    p.write_text(content)
    _git(["add", fname], wt_path)
    _git(["commit", "-q", "-m", msg], wt_path)


def _build(tmp_path, repo, base, runner, integration_retries=2):
    return build_integration(
        contracts=load_contracts(), runner=runner, verifier=_green_verifier,
        repo=repo, worktrees_root=tmp_path / "wts", run_id="run-1",
        base_sha=base, state_dir=tmp_path / "state",
        plan_review_retries=2, exec_review_retries=2, attempt_cap=4,
        integration_retries=integration_retries)


def test_team_runner_creates_worktree_and_persists_artifacts(tmp_path):
    repo = tmp_path / "repo"; base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, _ = _build(tmp_path, repo, base, runner)

    results = team_runner([_charter("team-01")], {"iteration": 1})

    assert len(results) == 1 and results[0].passed
    wt = tmp_path / "wts" / "run-1" / "team-01"
    assert wt.exists()
    teamdir = tmp_path / "state" / "iterations" / "iter-001" / "teams" / "team-01"
    for fname in ("plan.json", "execution.json", "exec_review.json", "attempts.json"):
        assert (teamdir / fname).exists(), fname


def test_integrate_merges_passing_team_with_real_sha(tmp_path):
    repo = tmp_path / "repo"; base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)

    results = team_runner([_charter("team-01")], {"iteration": 1})
    wt = tmp_path / "wts" / "run-1" / "team-01"
    _commit_in_worktree(wt, "a.txt", "work", "team work")

    outcome = integrate_fn(results, {"iteration": 1})

    assert outcome.merged == ["team-01"]
    assert outcome.rejected == []
    assert "+" not in outcome.final_base_sha
    assert re.fullmatch(r"[0-9a-f]{40}", outcome.final_base_sha)
    assert outcome.final_base_sha != base


def test_integrate_rejects_when_reviewer_declines(tmp_path):
    repo = tmp_path / "repo"; base = _seed_repo(repo)
    runner = _passing_runner(approved=True)
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)
    results = team_runner([_charter("team-01")], {"iteration": 1})
    wt = tmp_path / "wts" / "run-1" / "team-01"
    _commit_in_worktree(wt, "a.txt", "work", "team work")

    # flip reviewer to decline for the reverify step
    runner.responses["execution-reviewer"] = {"approved": False, "reasons": ["no"]}
    outcome = integrate_fn(results, {"iteration": 1})

    assert outcome.rejected == ["team-01"]
    assert outcome.merged == []


def test_failed_team_worktree_removed(tmp_path):
    repo = tmp_path / "repo"; base = _seed_repo(repo)
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": False, "feedback": "too vague"},
        "executor": {"commits": []},
        "execution-reviewer": {"approved": True, "reasons": []},
    })
    team_runner, integrate_fn = build_integration(
        contracts=load_contracts(), runner=runner, verifier=_green_verifier,
        repo=repo, worktrees_root=tmp_path / "wts", run_id="run-1",
        base_sha=base, state_dir=tmp_path / "state",
        plan_review_retries=1, exec_review_retries=1, attempt_cap=10,
        integration_retries=2)

    results = team_runner([_charter("team-01")], {"iteration": 1})

    assert not results[0].passed
    assert not (tmp_path / "wts" / "run-1" / "team-01").exists()
    outcome = integrate_fn(results, {"iteration": 1})
    assert outcome.merged == [] and outcome.rejected == []
