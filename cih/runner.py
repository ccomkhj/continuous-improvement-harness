import argparse
import sys
from pathlib import Path
from cih.config import RunConfig

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cih", description="Continuous Improvement Harness")
    p.add_argument("--mode", choices=["fixed-N", "until-converged"])
    p.add_argument("--iterations", type=int, default=None)
    p.add_argument("--target-repo", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--focus", action="append", default=[], dest="focus_areas")
    p.add_argument("--value-threshold", type=float, default=0.5, dest="value_threshold")
    p.add_argument("--max-iterations", type=int, default=25)
    p.add_argument("--report", action="store_true",
                   help="write/update report.html each iteration")
    p.add_argument("--non-interactive", "--yes", action="store_true", dest="non_interactive",
                   help="skip the scoping interview and build the run from flags (requires --mode)")
    return p.parse_args(argv)

def build_config(ns: argparse.Namespace) -> RunConfig:
    if ns.mode is None:
        from cih.config import ConfigError
        raise ConfigError("--mode is required in --non-interactive mode")
    return RunConfig.create(
        mode=ns.mode, iterations=ns.iterations, target_repo=ns.target_repo,
        state_dir=ns.state_dir, focus_areas=ns.focus_areas,
        value_threshold=ns.value_threshold, max_iterations=ns.max_iterations)

def build_orchestrator(cfg: RunConfig, runner, run_id: str = "run-1", report: bool = False):
    """Assemble a fully-wired Orchestrator from a config and an agent runner.

    This is the testable seam: pass a StubRunner to exercise the whole assembly
    (contracts -> integration -> orchestrator) without a real LLM. The TDD
    verifier is bound per-team inside build_integration (verifier=None) so each
    team's worktree gets its own mechanical pytest gate.
    """
    from cih.agents import invoke
    from cih.integration import build_integration
    from cih.orchestrator import Orchestrator
    from cih.progress import append_progress
    from cih.roles import load_contracts
    from cih.safety import assert_clean_tree, run_git

    contracts = load_contracts()
    state_dir = Path(cfg.state_dir)

    # Append-only audit trail of every git command (spec §11).
    log = lambda line: append_progress(cfg.state_dir, line)

    # Enforced preflight: refuse to run against a dirty target tree (spec §11).
    assert_clean_tree(cfg.target_repo, log=log)
    base_sha = run_git(["rev-parse", "HEAD"], cwd=cfg.target_repo).strip()

    team_runner, integrate_fn = build_integration(
        contracts=contracts, runner=runner, verifier=None,
        repo=cfg.target_repo, worktrees_root=state_dir / "worktrees",
        run_id=run_id, base_sha=base_sha, state_dir=cfg.state_dir,
        plan_review_retries=cfg.plan_review_retries,
        exec_review_retries=cfg.exec_review_retries,
        attempt_cap=cfg.per_team_attempt_cap,
        integration_retries=cfg.integration_retries,
        tdd_adapter=cfg.tdd_adapter, log=log)

    def high_planner_fn(ctx):
        return invoke(runner, contracts["high-planner"], ctx)

    from cih.report import write_report
    on_iter = (lambda: write_report(cfg.state_dir)) if report else None
    return Orchestrator(cfg, high_planner_fn=high_planner_fn,
                        team_runner_fn=team_runner, integrate_fn=integrate_fn,
                        run_id=run_id, on_iteration_end=on_iter)

def install_skill_cmd(argv: list[str]) -> int:
    from cih.install import install_skill, DEFAULT_DEST
    p = argparse.ArgumentParser(
        prog="cih install-skill",
        description="Install the interactive cih skill + agents into a Claude Code config dir")
    p.add_argument("--dest", default=str(DEFAULT_DEST),
                   help=f"Claude config dir to install into (default: {DEFAULT_DEST})")
    ns = p.parse_args(argv)
    written = install_skill(ns.dest)
    print(f"cih: installed skill + {len(written) - 1} agents into {ns.dest}")
    for path in written:
        print(f"  {path}")
    return 0

def main(argv: list[str] | None = None) -> int:
    from cih.agents import ClaudeCliRunner
    from cih.config import ConfigError
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "install-skill":
        return install_skill_cmd(argv[1:])
    ns = parse_args(argv)

    if ns.non_interactive:
        cfg = build_config(ns)
    else:
        if not sys.stdin.isatty():
            raise ConfigError(
                "interactive scoping needs a TTY — pass --non-interactive to run from flags")
        from cih.scoping import QuestionaryAsker, run_scoping_interview
        cfg = run_scoping_interview(ns.target_repo, ns.state_dir, QuestionaryAsker())

    runner = ClaudeCliRunner(cwd=cfg.target_repo)
    orch = build_orchestrator(cfg, runner, report=ns.report)
    summary = orch.run()
    print(f"cih: mode={cfg.mode} target={cfg.target_repo} state={cfg.state_dir}")
    print(f"cih: summary={summary}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
