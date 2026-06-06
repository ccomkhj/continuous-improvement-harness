import subprocess
import pytest
from pathlib import Path
from cih.runner import parse_args, build_config, build_orchestrator
from cih.agents import StubRunner
from cih.config import RunConfig
from cih.safety import assert_clean_tree, GitError

def test_parse_args_fixed_n(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "fixed-N", "--iterations", "3",
                     "--target-repo", str(t), "--state-dir", str(s),
                     "--focus", "tests", "--focus", "perf"])
    cfg = build_config(ns)
    assert cfg.mode == "fixed-N"
    assert cfg.iterations == 3
    assert cfg.focus_areas == ["tests", "perf"]

def test_parse_args_until_converged(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "until-converged",
                     "--target-repo", str(t), "--state-dir", str(s)])
    cfg = build_config(ns)
    assert cfg.mode == "until-converged"
    assert cfg.iterations is None


def _seed_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=str(path), check=True)
    (path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(path), check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(path),
                          capture_output=True, text=True).stdout.strip()


def test_assert_clean_tree_passes_on_clean_repo(tmp_path):
    repo = tmp_path / "repo"; _seed_repo(repo)
    assert assert_clean_tree(repo) is None


def test_assert_clean_tree_raises_on_dirty_repo(tmp_path):
    repo = tmp_path / "repo"; _seed_repo(repo)
    (repo / "f.txt").write_text("dirty")  # uncommitted change to a tracked file
    with pytest.raises(GitError, match="not clean"):
        assert_clean_tree(repo)


def test_build_orchestrator_aborts_on_dirty_target(tmp_path):
    repo = tmp_path / "repo"; _seed_repo(repo)
    (repo / "f.txt").write_text("dirty")  # make the target dirty before the run
    state = tmp_path / "state"; state.mkdir()
    cfg = RunConfig.create(mode="fixed-N", iterations=1,
                           target_repo=str(repo), state_dir=str(state))
    stub = StubRunner(responses={
        "high-planner": {"opportunities": [], "charters": []}})

    with pytest.raises(GitError):
        build_orchestrator(cfg, stub)

    # preflight runs before the orchestrator is constructed/run, so no run started
    assert not (state / "run.json").exists()


def test_build_orchestrator_runs_end_to_end(tmp_path):
    """build_orchestrator assembles a runnable orchestrator from cfg + runner.

    No charters => no teams, so this exercises the full wiring (contracts ->
    integration -> orchestrator) without needing real worktree commits.
    """
    repo = tmp_path / "repo"; _seed_repo(repo)
    state = tmp_path / "state"; state.mkdir()
    cfg = RunConfig.create(mode="fixed-N", iterations=1,
                           target_repo=str(repo), state_dir=str(state))
    stub = StubRunner(responses={
        "high-planner": {"opportunities": [], "charters": []}})

    orch = build_orchestrator(cfg, stub)
    summary = orch.run()

    assert summary["iterations_run"] == 1
    assert (state / "run.json").exists()


def test_build_orchestrator_writes_progress_md(tmp_path):
    """build_orchestrator wires the progress sink, so a run that creates a
    worktree records git commands to <state_dir>/progress.md (spec §11)."""
    repo = tmp_path / "repo"; _seed_repo(repo)
    state = tmp_path / "state"; state.mkdir()
    cfg = RunConfig.create(mode="fixed-N", iterations=1,
                           target_repo=str(repo), state_dir=str(state))
    charter = {"id": "team-01", "goal": "x", "opportunity_fp": "fp-1",
               "impact_manifest": {"intended_files": ["a.txt"]}}
    stub = StubRunner(responses={
        "high-planner": {"opportunities": [], "charters": [charter]},
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": []},
        "execution-reviewer": {"approved": True, "reasons": []},
    })

    build_orchestrator(cfg, stub).run()

    progress = state / "progress.md"
    assert progress.exists()
    assert progress.read_text().strip() != ""
