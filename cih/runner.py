import argparse
import sys
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

def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv if argv is not None else sys.argv[1:])
    cfg = build_config(ns)
    # Real wiring (orchestrator + ClaudeCliRunner + worktree/merge integration) is
    # assembled here; see Task 19 for the integration glue.
    print(f"cih: mode={cfg.mode} target={cfg.target_repo} state={cfg.state_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
