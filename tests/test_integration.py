# tests/test_integration.py
import re
import subprocess
from pathlib import Path

from cih.agents import StubRunner
from cih.integration import build_integration
from cih.progress import append_progress
from cih.roles import load_contracts
from cih.tdd_verifier import TddVerdict


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout.strip()


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
    return StubRunner(
        responses={
            "planner": {"tasks": ["t1"]},
            "plan-reviewer": {"approved": True, "feedback": ""},
            "executor": {"commits": []},
            "execution-reviewer": {"approved": approved, "reasons": [] if approved else ["no"]},
        }
    )


def _charter(team_id, intended_files=("a.txt",)):
    return {
        "id": team_id,
        "goal": "x",
        "opportunity_fp": "fp-" + team_id,
        "impact_manifest": {"intended_files": list(intended_files)},
    }


def _commit_in_worktree(wt_path, fname, content, msg):
    p = Path(wt_path) / fname
    p.write_text(content)
    _git(["add", fname], wt_path)
    _git(["commit", "-q", "-m", msg], wt_path)


def _build(tmp_path, repo, base, runner, integration_retries=2):
    return build_integration(
        contracts=load_contracts(),
        runner=runner,
        verifier=_green_verifier,
        repo=repo,
        worktrees_root=tmp_path / "wts",
        run_id="run-1",
        base_sha=base,
        state_dir=tmp_path / "state",
        plan_review_retries=2,
        exec_review_retries=2,
        attempt_cap=4,
        integration_retries=integration_retries,
    )


def _int_ref(repo):
    return _git(["rev-parse", "cih/run-1/integration"], repo)


def _reachable(repo, fname):
    """True if fname exists in the integration branch tip tree."""
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"cih/run-1/integration:{fname}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def test_team_runner_creates_worktree_and_persists_artifacts(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, _ = _build(tmp_path, repo, base, runner)

    results = team_runner([_charter("team-01")], {"iteration": 1})

    assert len(results) == 1 and results[0].passed
    wt = tmp_path / "wts" / "run-1" / "iter-001" / "team-01"
    assert wt.exists()
    teamdir = tmp_path / "state" / "iterations" / "iter-001" / "teams" / "team-01"
    for fname in ("plan.json", "execution.json", "exec_review.json", "attempts.json"):
        assert (teamdir / fname).exists(), fname


def test_team_branch_is_iteration_scoped(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, _ = _build(tmp_path, repo, base, runner)
    team_runner([_charter("team-01")], {"iteration": 1})
    # branch carries the iteration so iter-2's team-01 cannot collide
    assert _git(["rev-parse", "--verify", "cih/run-1/iter-001/team-01"], repo)


def test_integrate_merges_passing_team_with_real_sha(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)

    results = team_runner([_charter("team-01")], {"iteration": 1})
    wt = tmp_path / "wts" / "run-1" / "iter-001" / "team-01"
    _commit_in_worktree(wt, "a.txt", "work", "team work")

    outcome = integrate_fn(results, {"iteration": 1})

    assert outcome.merged == ["team-01"]
    assert outcome.rejected == []
    assert "+" not in outcome.final_base_sha
    assert re.fullmatch(r"[0-9a-f]{40}", outcome.final_base_sha)
    assert outcome.final_base_sha != base
    # merge preserves the executor commit; a.txt reachable from the integration ref
    assert _reachable(repo, "a.txt")


def test_integrate_rejects_when_reviewer_declines(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner(approved=True)
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)
    results = team_runner([_charter("team-01")], {"iteration": 1})
    wt = tmp_path / "wts" / "run-1" / "iter-001" / "team-01"
    _commit_in_worktree(wt, "a.txt", "work", "team work")

    # flip reviewer to decline for the reverify step
    runner.responses["execution-reviewer"] = {"approved": False, "reasons": ["no"]}
    outcome = integrate_fn(results, {"iteration": 1})

    assert outcome.rejected == ["team-01"]
    assert outcome.merged == []
    # integration worktree was reset to base; the change did NOT land
    assert _int_ref(repo) == base
    assert not _reachable(repo, "a.txt")


def test_failed_team_worktree_removed(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = StubRunner(
        responses={
            "planner": {"tasks": ["t1"]},
            "plan-reviewer": {"approved": False, "feedback": "too vague"},
            "executor": {"commits": []},
            "execution-reviewer": {"approved": True, "reasons": []},
        }
    )
    team_runner, integrate_fn = build_integration(
        contracts=load_contracts(),
        runner=runner,
        verifier=_green_verifier,
        repo=repo,
        worktrees_root=tmp_path / "wts",
        run_id="run-1",
        base_sha=base,
        state_dir=tmp_path / "state",
        plan_review_retries=1,
        exec_review_retries=1,
        attempt_cap=10,
        integration_retries=2,
    )

    results = team_runner([_charter("team-01")], {"iteration": 1})

    assert not results[0].passed
    assert not (tmp_path / "wts" / "run-1" / "iter-001" / "team-01").exists()
    outcome = integrate_fn(results, {"iteration": 1})
    assert outcome.merged == [] and outcome.rejected == []


def test_crashing_run_team_does_not_leak_worktree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, _ = _build(tmp_path, repo, base, runner)

    import cih.integration as integ

    def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(integ, "run_team", boom)
    results = team_runner([_charter("team-01")], {"iteration": 1})

    assert len(results) == 1 and not results[0].passed
    assert "team crashed" in results[0].reason
    # the worktree created for the crashing team is gone, not leaked
    assert not (tmp_path / "wts" / "run-1" / "iter-001" / "team-01").exists()


def test_pending_resets_per_iteration(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)

    # iteration 1: a passing team
    r1 = team_runner([_charter("team-01")], {"iteration": 1})
    wt1 = tmp_path / "wts" / "run-1" / "iter-001" / "team-01"
    _commit_in_worktree(wt1, "a.txt", "work", "team work")
    out1 = integrate_fn(r1, {"iteration": 1})
    assert out1.merged == ["team-01"]

    # iteration 2: a different team; iteration-1's team must NOT reappear
    r2 = team_runner([_charter("team-02")], {"iteration": 2})
    wt2 = tmp_path / "wts" / "run-1" / "iter-002" / "team-02"
    _commit_in_worktree(wt2, "b.txt", "work2", "team2 work")
    out2 = integrate_fn(r2, {"iteration": 2})
    assert out2.merged == ["team-02"]
    assert "team-01" not in out2.merged and "team-01" not in out2.rejected


def test_two_iterations_accumulate_changes(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)

    # iteration 1: team adds a.txt
    r1 = team_runner([_charter("team-01")], {"iteration": 1})
    wt1 = tmp_path / "wts" / "run-1" / "iter-001" / "team-01"
    _commit_in_worktree(wt1, "a.txt", "alpha", "add a")
    out1 = integrate_fn(r1, {"iteration": 1})
    assert out1.merged == ["team-01"]
    head_after_1 = _int_ref(repo)
    assert head_after_1 == out1.final_base_sha
    assert head_after_1 != base
    assert _reachable(repo, "a.txt")

    # iteration 2: team branches off the NEW head and adds b.txt
    r2 = team_runner([_charter("team-01", intended_files=("b.txt",))], {"iteration": 2})
    wt2 = tmp_path / "wts" / "run-1" / "iter-002" / "team-01"
    # the team worktree must already contain iteration 1's a.txt (built on new head)
    assert (Path(wt2) / "a.txt").exists()
    _commit_in_worktree(wt2, "b.txt", "beta", "add b")
    out2 = integrate_fn(r2, {"iteration": 2})
    assert out2.merged == ["team-01"]
    head_after_2 = _int_ref(repo)
    assert head_after_2 == out2.final_base_sha
    assert head_after_2 != head_after_1
    # iteration 2 built ON TOP of iteration 1: both files reachable
    assert _reachable(repo, "a.txt")
    assert _reachable(repo, "b.txt")


def test_teardown_removes_worktrees_keeps_branches(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)

    # one passing iteration with a real commit so the team worktree is kept
    results = team_runner([_charter("team-01")], {"iteration": 1})
    team_wt = tmp_path / "wts" / "run-1" / "iter-001" / "team-01"
    _commit_in_worktree(team_wt, "a.txt", "work", "team work")
    outcome = integrate_fn(results, {"iteration": 1})
    assert outcome.merged == ["team-01"]

    int_wt = tmp_path / "wts" / "run-1" / "integration"
    # both worktree dirs exist before teardown
    assert int_wt.exists()
    assert team_wt.exists()

    integrate_fn.teardown()

    # worktree dirs are gone
    assert not int_wt.exists()
    assert not team_wt.exists()
    # no cih/run-1 worktree entries remain registered
    wt_list = _git(["worktree", "list"], repo)
    assert "run-1" not in wt_list
    # branch refs are preserved for reconcile/resume
    assert _git(["rev-parse", "--verify", "cih/run-1/integration"], repo)
    assert _git(["rev-parse", "--verify", "cih/run-1/iter-001/team-01"], repo)

    # idempotent: a second call must not raise
    integrate_fn.teardown()


def test_progress_log_records_git_commands(tmp_path):
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    state_dir = tmp_path / "state"
    team_runner, _ = build_integration(
        contracts=load_contracts(),
        runner=runner,
        verifier=_green_verifier,
        repo=repo,
        worktrees_root=tmp_path / "wts",
        run_id="run-1",
        base_sha=base,
        state_dir=state_dir,
        plan_review_retries=2,
        exec_review_retries=2,
        attempt_cap=4,
        integration_retries=2,
        log=lambda line: append_progress(state_dir, line),
    )

    team_runner([_charter("team-01")], {"iteration": 1})

    progress = state_dir / "progress.md"
    assert progress.exists()
    text = progress.read_text()
    assert "git -C" in text
    assert "worktree add" in text


def test_integration_suite_timeout_rejects_team_cleanly(tmp_path, monkeypatch):
    """If the integration suite run times out, the team is rejected (not merged,
    not crashed) and the run continues."""
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)
    results = team_runner([_charter("team-01")], {"iteration": 1})
    wt = tmp_path / "wts" / "run-1" / "iter-001" / "team-01"
    _commit_in_worktree(wt, "a.txt", "work", "team work")

    import cih.integration as integ

    real_run = subprocess.run

    def fake_run(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if argv and "pytest" in argv:  # only the integration suite call times out
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout"))
        return real_run(*args, **kwargs)  # git operations run for real

    monkeypatch.setattr(integ.subprocess, "run", fake_run)
    outcome = integrate_fn(results, {"iteration": 1})

    assert outcome.merged == []
    assert outcome.rejected == ["team-01"]
    assert _int_ref(repo) == base


def test_later_team_rejection_preserves_earlier_merge(tmp_path):
    """Two teams pass TDD in one iteration; the first merges cleanly, the second
    is rejected at integration (its merge breaks the suite). The first team's
    merge must survive — and the integration worktree must stay consistent so a
    LATER iteration can still merge."""
    repo = tmp_path / "repo"
    base = _seed_repo(repo)
    runner = _passing_runner()
    team_runner, integrate_fn = _build(tmp_path, repo, base, runner)

    # iteration 1: team-01 adds a plain file (suite => no tests, ok),
    # team-02 adds a FAILING test (suite => fails once merged).
    r1 = team_runner(
        [
            _charter("team-01", intended_files=("a.txt",)),
            _charter("team-02", intended_files=("test_b.py",)),
        ],
        {"iteration": 1},
    )
    wt1 = tmp_path / "wts" / "run-1" / "iter-001" / "team-01"
    wt2 = tmp_path / "wts" / "run-1" / "iter-001" / "team-02"
    _commit_in_worktree(wt1, "a.txt", "alpha", "add a")
    _commit_in_worktree(wt2, "test_b.py", "def test_b():\n    assert False\n", "add failing test")

    out1 = integrate_fn(r1, {"iteration": 1})
    assert out1.merged == ["team-01"]
    assert out1.rejected == ["team-02"]
    assert _reachable(repo, "a.txt")
    assert not _reachable(repo, "test_b.py")
    head_after_1 = _int_ref(repo)
    assert head_after_1 == out1.final_base_sha

    # iteration 2: a clean team must still be able to merge on top — proving the
    # integration worktree wasn't left inconsistent by the iteration-1 rejection.
    r2 = team_runner([_charter("team-03", intended_files=("c.txt",))], {"iteration": 2})
    wt3 = tmp_path / "wts" / "run-1" / "iter-002" / "team-03"
    _commit_in_worktree(wt3, "c.txt", "gamma", "add c")
    out2 = integrate_fn(r2, {"iteration": 2})
    assert out2.merged == ["team-03"]
    assert _reachable(repo, "a.txt")
    assert _reachable(repo, "c.txt")
