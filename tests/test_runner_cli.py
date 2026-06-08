import subprocess
import pytest
from pathlib import Path
from cih.runner import parse_args, build_config, build_orchestrator, main
from cih.agents import StubRunner
from cih.config import RunConfig, ConfigError
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


def test_successful_run_leaves_no_worktree_dirs(tmp_path):
    """A successful orchestrator run tears down its worktree directories at the
    end, so nothing accumulates under <state_dir>/worktrees/<run_id>/."""
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

    # the actual worktree leaf dirs are gone (an empty iter parent dir may remain)
    assert not (state / "worktrees" / "run-1" / "integration").exists()
    assert not (state / "worktrees" / "run-1" / "iter-001" / "team-01").exists()
    # git no longer tracks any cih/run-1 worktree
    wt_list = subprocess.run(["git", "worktree", "list"], cwd=str(repo),
                             capture_output=True, text=True).stdout
    assert "run-1" not in wt_list


def test_parse_args_report_flag(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "fixed-N", "--iterations", "1",
                     "--target-repo", str(t), "--state-dir", str(s), "--report"])
    assert ns.report is True


def test_build_orchestrator_report_emits_html(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); _seed_repo(repo)
    state = tmp_path / "state"; state.mkdir()
    ns = parse_args(["--mode", "fixed-N", "--iterations", "1",
                     "--target-repo", str(repo), "--state-dir", str(state), "--report"])
    cfg = build_config(ns)
    stub = StubRunner(responses={"high-planner": {"opportunities": [], "charters": []}})
    orch = build_orchestrator(cfg, stub, report=ns.report)
    orch.run()
    report = state / "report.html"
    assert report.exists()
    # The FINAL fire happens after the done persist, so the terminal report
    # shows the done badge and drops the in_progress meta-refresh (liveness).
    text = report.read_text()
    assert ">done<" in text
    assert 'http-equiv="refresh"' not in text


def test_parse_args_mode_optional_for_interactive(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--target-repo", str(t), "--state-dir", str(s)])
    assert ns.mode is None
    assert ns.non_interactive is False


def test_parse_args_non_interactive_flag(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "until-converged", "--target-repo", str(t),
                     "--state-dir", str(s), "--non-interactive"])
    assert ns.non_interactive is True


def test_parse_args_yes_is_alias_for_non_interactive(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "until-converged", "--target-repo", str(t),
                     "--state-dir", str(s), "--yes"])
    assert ns.non_interactive is True


def test_build_config_requires_mode_when_non_interactive(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--target-repo", str(t), "--state-dir", str(s), "--non-interactive"])
    with pytest.raises(ConfigError, match="--mode is required"):
        build_config(ns)


def test_build_config_non_interactive_parity(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "fixed-N", "--iterations", "2",
                     "--target-repo", str(t), "--state-dir", str(s),
                     "--focus", "tests", "--value-threshold", "0.7", "--non-interactive"])
    cfg = build_config(ns)
    assert cfg.mode == "fixed-N"
    assert cfg.iterations == 2
    assert cfg.focus_areas == ["tests"]
    assert cfg.value_threshold == 0.7


def test_main_interactive_requires_tty(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; _seed_repo(repo)
    state = tmp_path / "state"; state.mkdir()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ConfigError, match="needs a TTY"):
        main(["--target-repo", str(repo), "--state-dir", str(state)])


def test_main_interactive_clean_exit_on_cancel(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"; _seed_repo(repo)
    state = tmp_path / "state"; state.mkdir()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _cancel(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr("cih.scoping.run_scoping_interview", _cancel)
    code = main(["--target-repo", str(repo), "--state-dir", str(state)])
    assert code == 130
    err = capsys.readouterr().err
    assert "cancel" in err.lower()


# --- run.json hand-off (scope in one session, run in a fresh workspace) ---

def test_parse_args_from_run_json_makes_paths_optional(tmp_path):
    """--from-run-json carries target/state, so they aren't required on the CLI."""
    from cih.runner import parse_args
    p = tmp_path / "run.json"
    ns = parse_args(["--from-run-json", str(p)])
    assert ns.from_run_json == str(p)
    assert ns.target_repo is None and ns.state_dir is None


def test_write_run_json_cmd_writes_scoped_config(tmp_path):
    """`cih write-run-json <flags>` serialises a validated config to
    <state_dir>/run.json without running, so a scoping session can hand off."""
    from cih.runner import main, load_run_json
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    code = main(["write-run-json", "--mode", "fixed-N", "--iterations", "2",
                 "--target-repo", str(t), "--state-dir", str(s),
                 "--focus", "tests", "--value-threshold", "0.7"])
    assert code == 0
    run_json = s / "run.json"
    assert run_json.exists()
    cfg = load_run_json(str(run_json))
    assert cfg.mode == "fixed-N"
    assert cfg.iterations == 2
    assert cfg.focus_areas == ["tests"]
    assert cfg.value_threshold == 0.7
    assert cfg.target_repo == str(t)
    assert cfg.state_dir == str(s)


def test_write_run_json_cmd_requires_mode(tmp_path):
    from cih.runner import main
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    with pytest.raises(ConfigError, match="--mode is required"):
        main(["write-run-json", "--target-repo", str(t), "--state-dir", str(s)])


def test_load_run_json_round_trips(tmp_path):
    """load_run_json reconstructs the exact RunConfig that was persisted."""
    from cih.runner import load_run_json
    from cih.state import write_state, StateHeader
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    cfg = RunConfig.create(mode="until-converged", target_repo=str(t),
                           state_dir=str(s), focus_areas=["perf", "tests"],
                           value_threshold=0.3)
    p = s / "run.json"
    write_state(p, StateHeader("run-1", None, None, None, "scoped", "orchestrator"),
                cfg.to_dict())
    assert load_run_json(str(p)).to_dict() == cfg.to_dict()


def test_load_run_json_accepts_terminal_run_body(tmp_path):
    """A completed run nests config under body.config; load_run_json handles it."""
    from cih.runner import load_run_json
    from cih.state import write_state, StateHeader
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    cfg = RunConfig.create(mode="fixed-N", iterations=1, target_repo=str(t),
                           state_dir=str(s))
    p = s / "run.json"
    write_state(p, StateHeader("run-1", None, None, None, "done", "orchestrator"),
                {"config": cfg.to_dict(), "summary": {"iterations_run": 1}})
    assert load_run_json(str(p)).to_dict() == cfg.to_dict()


def test_main_from_run_json_loads_config_without_paths(tmp_path, monkeypatch):
    """main(--from-run-json) loads the persisted cfg and runs it, with no
    --target-repo/--state-dir on the command line."""
    from cih import runner as runner_mod
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    runner_mod.main(["write-run-json", "--mode", "fixed-N", "--iterations", "1",
                     "--target-repo", str(t), "--state-dir", str(s)])

    captured = {}

    class _StubOrch:
        def run(self):
            return {"iterations_run": 0}

    def _fake_build(cfg, runner, report=False):
        captured["cfg"] = cfg
        return _StubOrch()

    monkeypatch.setattr(runner_mod, "build_orchestrator", _fake_build)
    monkeypatch.setattr("cih.agents.ClaudeCliRunner", lambda cwd: object())

    code = runner_mod.main(["--from-run-json", str(s / "run.json")])
    assert code == 0
    assert captured["cfg"].mode == "fixed-N"
    assert captured["cfg"].target_repo == str(t)


def test_main_from_run_json_target_repo_override(tmp_path, monkeypatch):
    """An explicit --target-repo alongside --from-run-json overrides the file's
    target (so a run hands off to a fresh workspace checkout, not the original)."""
    from cih import runner as runner_mod
    t = tmp_path / "orig"; s = tmp_path / "s"; ws = tmp_path / "workspace"
    t.mkdir(); s.mkdir(); ws.mkdir()
    runner_mod.main(["write-run-json", "--mode", "until-converged",
                     "--target-repo", str(t), "--state-dir", str(s),
                     "--focus", "tests"])

    captured = {}

    class _StubOrch:
        def run(self):
            return {}

    def _fake_build(cfg, runner, report=False):
        captured["cfg"] = cfg
        return _StubOrch()

    monkeypatch.setattr(runner_mod, "build_orchestrator", _fake_build)
    monkeypatch.setattr("cih.agents.ClaudeCliRunner", lambda cwd: object())

    code = runner_mod.main(["--from-run-json", str(s / "run.json"),
                            "--target-repo", str(ws)])
    assert code == 0
    assert captured["cfg"].target_repo == str(ws)   # overridden
    assert captured["cfg"].state_dir == str(s)       # kept from file
    assert captured["cfg"].focus_areas == ["tests"]  # kept from file
