import argparse
import sys
from pathlib import Path
from cih.config import RunConfig

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cih", description="Continuous Improvement Harness")
    p.add_argument("--mode", required=True, choices=["fixed-N", "until-converged"])
    p.add_argument("--iterations", type=int, default=None)
    p.add_argument("--target-repo", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--focus", action="append", default=[], dest="focus_areas")
    p.add_argument("--max-iterations", type=int, default=25)
    return p.parse_args(argv)

def build_config(ns: argparse.Namespace) -> RunConfig:
    return RunConfig.create(
        mode=ns.mode, iterations=ns.iterations, target_repo=ns.target_repo,
        state_dir=ns.state_dir, focus_areas=ns.focus_areas,
        max_iterations=ns.max_iterations)

def build_orchestrator(cfg: RunConfig, runner, run_id: str = "run-1"):
    """Assemble a fully-wired Orchestrator from a config and an agent runner.

    This is the testable seam: pass a StubRunner to exercise the whole assembly
    (contracts -> integration -> orchestrator) without a real LLM. The TDD
    verifier is bound per-team inside build_integration (verifier=None) so each
    team's worktree gets its own mechanical pytest gate.
    """
    from cih.agents import invoke
    from cih.integration import build_integration
    from cih.orchestrator import Orchestrator
    from cih.roles import load_contracts
    from cih.safety import run_git

    contracts = load_contracts()
    base_sha = run_git(["rev-parse", "HEAD"], cwd=cfg.target_repo).strip()
    state_dir = Path(cfg.state_dir)

    team_runner, integrate_fn = build_integration(
        contracts=contracts, runner=runner, verifier=None,
        repo=cfg.target_repo, worktrees_root=state_dir / "worktrees",
        run_id=run_id, base_sha=base_sha, state_dir=cfg.state_dir,
        plan_review_retries=cfg.plan_review_retries,
        exec_review_retries=cfg.exec_review_retries,
        attempt_cap=cfg.per_team_attempt_cap,
        integration_retries=cfg.integration_retries,
        tdd_adapter=cfg.tdd_adapter)

    def high_planner_fn(ctx):
        return invoke(runner, contracts["high-planner"], ctx)

    return Orchestrator(cfg, high_planner_fn=high_planner_fn,
                        team_runner_fn=team_runner, integrate_fn=integrate_fn,
                        run_id=run_id)

def main(argv: list[str] | None = None) -> int:
    from cih.agents import ClaudeCliRunner
    ns = parse_args(argv if argv is not None else sys.argv[1:])
    cfg = build_config(ns)
    runner = ClaudeCliRunner(cwd=cfg.target_repo)
    orch = build_orchestrator(cfg, runner)
    summary = orch.run()
    print(f"cih: mode={cfg.mode} target={cfg.target_repo} state={cfg.state_dir}")
    print(f"cih: summary={summary}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
