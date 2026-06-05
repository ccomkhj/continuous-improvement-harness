import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from cih.safety import run_git

@dataclass
class TddVerdict:
    eligible: bool          # could we mechanically prove anything?
    passed: bool
    reason: str = ""
    red_failed: bool = False
    green_passed: bool = False
    full_suite_passed: bool = False
    suspicious_assertions: bool = False  # routed to execution-reviewer
    command: list = field(default_factory=list)
    red_sha: str = ""
    green_sha: str = ""

def _checkout(repo: Path, sha: str):
    run_git(["checkout", "-q", sha], cwd=repo)

def _run(repo: Path, cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True).returncode

def _changed_paths(repo: Path, base: str, head: str) -> list[str]:
    out = run_git(["diff", "--name-only", base, head], cwd=repo)
    return [p for p in out.splitlines() if p.strip()]

def _is_test_path(p: str, declared: list[str]) -> bool:
    name = Path(p).name
    return p in declared or name.startswith("test_") or name.endswith("_test.py")

def verify_tdd(repo: Path, red_sha: str, green_sha: str,
               test_command: list[str], declared_test_paths: list[str],
               adapter: str = "pytest") -> TddVerdict:
    repo = Path(repo)
    v = TddVerdict(eligible=(adapter == "pytest"), passed=False,
                   command=test_command, red_sha=red_sha, green_sha=green_sha)
    if not v.eligible:
        v.reason = f"no mechanical adapter for '{adapter}'; reviewer-only fallback"
        return v

    original = run_git(["rev-parse", "HEAD"], cwd=repo).strip()
    try:
        red_parent = run_git(["rev-parse", f"{red_sha}^"], cwd=repo).strip()

        # red commit must touch only test paths
        red_changes = _changed_paths(repo, red_parent, red_sha)
        if any(not _is_test_path(p, declared_test_paths) for p in red_changes):
            v.reason = "red commit changed non-test paths"
            return v

        # red commit's test command must FAIL
        _checkout(repo, red_sha)
        if _run(repo, test_command) == 0:
            v.reason = "red commit did not fail"
            return v
        v.red_failed = True

        # green commit must NOT modify any test path
        green_changes = _changed_paths(repo, red_sha, green_sha)
        if any(_is_test_path(p, declared_test_paths) for p in green_changes):
            v.reason = "green commit modified test paths"
            return v

        # obvious weakening hard-blocks; subtle ones flagged for reviewer
        red_test_blob = "\n".join(
            run_git(["show", f"{red_sha}:{p}"], cwd=repo)
            for p in red_changes if _is_test_path(p, declared_test_paths))
        if "@pytest.mark.skip" in red_test_blob or "pytest.skip(" in red_test_blob:
            v.reason = "test introduces skip markers"
            return v
        if "assert True" in red_test_blob:
            v.suspicious_assertions = True  # routed to reviewer, not hard-failed

        # green commit's test command must PASS, and full suite must pass
        _checkout(repo, green_sha)
        if _run(repo, test_command) != 0:
            v.reason = "green commit did not pass the declared test command"
            return v
        v.green_passed = True
        if _run(repo, ["python", "-m", "pytest", "-q"]) != 0:
            v.reason = "full suite failed at green commit"
            return v
        v.full_suite_passed = True

        v.passed = True
        v.reason = "red->green verified"
        return v
    finally:
        _checkout(repo, original)
