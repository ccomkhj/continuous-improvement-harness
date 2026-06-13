import argparse
import sys
from pathlib import Path

from cih.config import RunConfig


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="cih",
        description="Continuous Improvement Harness — interactive by default; "
        "use --non-interactive (with --mode) for scripted/CI runs.",
    )
    p.add_argument("--mode", choices=["fixed-N", "until-converged"])
    p.add_argument("--iterations", type=int, default=None)
    p.add_argument("--target-repo", default=None)
    p.add_argument("--state-dir", default=None)
    p.add_argument("--focus", action="append", default=[], dest="focus_areas")
    p.add_argument(
        "--brief",
        default="",
        help="free-form brief (surface, hotspot, success/proof bar, guardrails) — "
        "the high-signal steer the high-planner audit reads",
    )
    p.add_argument("--value-threshold", type=float, default=0.5, dest="value_threshold")
    p.add_argument("--max-iterations", type=int, default=25)
    p.add_argument("--report", action="store_true", help="write/update report.html each iteration")
    p.add_argument(
        "--from-run-json",
        default=None,
        dest="from_run_json",
        help="load the run config from an existing run.json (skips scoping "
        "and flag-building; --target-repo/--state-dir come from the file)",
    )
    p.add_argument(
        "--non-interactive",
        "--yes",
        action="store_true",
        dest="non_interactive",
        help="skip the scoping interview and build the run from flags (requires --mode)",
    )
    return p.parse_args(argv)


def _require_paths(ns: argparse.Namespace) -> None:
    from cih.config import ConfigError

    missing = [
        f
        for f, v in (("--target-repo", ns.target_repo), ("--state-dir", ns.state_dir))
        if v is None
    ]
    if missing:
        raise ConfigError(f"{' and '.join(missing)} required (or pass --from-run-json)")


def load_run_json(path: str) -> RunConfig:
    """Reconstruct a RunConfig from a persisted run.json (the hand-off artifact).

    Tolerates both the in-progress/scoped body (the config dict itself) and the
    terminal body ({"config": ..., "summary": ...}).
    """
    from cih.state import read_state

    doc = read_state(Path(path))
    body = doc["body"] if isinstance(doc, dict) and "body" in doc else doc
    cfg_dict = body["config"] if isinstance(body, dict) and "config" in body else body
    return RunConfig.from_dict(cfg_dict)


def write_run_json_cmd(argv: list[str]) -> int:
    """`cih write-run-json <flags>` — validate a config and persist it to
    <state_dir>/run.json without running, so an interactive scoping session can
    hand the run off to a fresh workspace via `--from-run-json`."""
    from cih.config import ConfigError
    from cih.state import StateHeader, write_state

    ns = parse_args(argv)
    if ns.mode is None:
        raise ConfigError("--mode is required for write-run-json")
    _require_paths(ns)
    cfg = build_config(ns)
    path = Path(cfg.state_dir) / "run.json"
    write_state(
        path, StateHeader("run-1", None, None, None, "scoped", "orchestrator"), cfg.to_dict()
    )
    print(f"cih: wrote {path}")
    return 0


def build_config(ns: argparse.Namespace) -> RunConfig:
    if ns.mode is None and ns.non_interactive:
        from cih.config import ConfigError

        raise ConfigError("--mode is required in --non-interactive mode")
    return RunConfig.create(
        mode=ns.mode,
        iterations=ns.iterations,
        target_repo=ns.target_repo,
        state_dir=ns.state_dir,
        focus_areas=ns.focus_areas,
        brief=ns.brief,
        value_threshold=ns.value_threshold,
        max_iterations=ns.max_iterations,
    )


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
    def log(line):
        return append_progress(cfg.state_dir, line)

    # Enforced preflight: refuse to run against a dirty target tree (spec §11).
    assert_clean_tree(cfg.target_repo, log=log)
    base_sha = run_git(["rev-parse", "HEAD"], cwd=cfg.target_repo).strip()

    team_runner, integrate_fn = build_integration(
        contracts=contracts,
        runner=runner,
        verifier=None,
        repo=cfg.target_repo,
        worktrees_root=state_dir / "worktrees",
        run_id=run_id,
        base_sha=base_sha,
        state_dir=cfg.state_dir,
        plan_review_retries=cfg.plan_review_retries,
        exec_review_retries=cfg.exec_review_retries,
        attempt_cap=cfg.per_team_attempt_cap,
        integration_retries=cfg.integration_retries,
        tdd_adapter=cfg.tdd_adapter,
        log=log,
    )

    def high_planner_fn(ctx):
        return invoke(runner, contracts["high-planner"], ctx)

    from cih.report import write_report

    on_iter = (lambda: write_report(cfg.state_dir)) if report else None
    return Orchestrator(
        cfg,
        high_planner_fn=high_planner_fn,
        team_runner_fn=team_runner,
        integrate_fn=integrate_fn,
        run_id=run_id,
        on_iteration_end=on_iter,
    )


def install_skill_cmd(argv: list[str]) -> int:
    from cih.install import DEFAULT_DEST, install_skill

    p = argparse.ArgumentParser(
        prog="cih install-skill",
        description="Install the interactive cih skill + agents into a Claude Code config dir",
    )
    p.add_argument(
        "--dest",
        default=str(DEFAULT_DEST),
        help=f"Claude config dir to install into (default: {DEFAULT_DEST})",
    )
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
    if argv and argv[0] == "write-run-json":
        return write_run_json_cmd(argv[1:])
    ns = parse_args(argv)

    if ns.from_run_json:
        cfg = load_run_json(ns.from_run_json)
        # explicit paths override the file (e.g. point the run at a fresh
        # workspace checkout while keeping the scoped intent from run.json)
        overrides = {
            k: v
            for k, v in (("target_repo", ns.target_repo), ("state_dir", ns.state_dir))
            if v is not None
        }
        if overrides:
            cfg = RunConfig.from_dict({**cfg.to_dict(), **overrides})
    elif ns.non_interactive:
        _require_paths(ns)
        cfg = build_config(ns)
    else:
        _require_paths(ns)
        if not sys.stdin.isatty():
            raise ConfigError(
                "interactive scoping needs a TTY — pass --non-interactive to run from flags"
            )
        from cih.scoping import QuestionaryAsker, run_scoping_interview

        try:
            cfg = run_scoping_interview(ns.target_repo, ns.state_dir, QuestionaryAsker())
        except KeyboardInterrupt:
            print("cih: scoping cancelled.", file=sys.stderr)
            return 130

    runner = ClaudeCliRunner(cwd=cfg.target_repo)
    orch = build_orchestrator(cfg, runner, report=ns.report)
    summary = orch.run()
    print(f"cih: mode={cfg.mode} target={cfg.target_repo} state={cfg.state_dir}")
    print(f"cih: summary={summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
