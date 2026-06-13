# cih/safety.py
import fnmatch
import os
import subprocess
from collections.abc import Callable
from pathlib import Path


class GitError(Exception):
    pass


# An unattended run must never hang on a stuck git process (e.g. a credential
# prompt or a wedged lock). Bound every git call; a true hang is unbounded, so a
# generous ceiling still catches it without tripping legitimately slow ops.
GIT_DEFAULT_TIMEOUT = 600.0


_FORBIDDEN = [
    ".cih/*",
    ".cih",
    ".harness/*",
    ".consult/*",
    "**/.cih/*",
    "*.pem",
    "*.key",
    "secrets/*",
    "secrets",
    "**/secrets/*",
]


def forbidden_paths() -> list[str]:
    return list(_FORBIDDEN)


def _matches(path: str, pat: str) -> bool:
    if fnmatch.fnmatch(path, pat):
        return True
    # "dir/*" should also catch the directory itself or anything under it
    if pat.endswith("/*"):
        base = pat[:-2]
        if path == base or path.startswith(base + "/"):
            return True
    return False


def validate_no_forbidden(paths: list[str], patterns: list[str]) -> None:
    for p in paths:
        norm = os.path.normpath(p)
        # reject absolute and traversal/outside-repo paths outright
        if os.path.isabs(p) or os.path.isabs(norm):
            raise GitError(f"path '{p}' is absolute and not allowed")
        if norm == ".." or norm.startswith(".." + os.sep) or norm.startswith("../"):
            raise GitError(f"path '{p}' escapes the repository via traversal")
        if ".." in norm.replace(os.sep, "/").split("/"):
            raise GitError(f"path '{p}' contains a '..' traversal segment")
        for pat in patterns:
            if _matches(p, pat) or _matches(norm, pat):
                raise GitError(f"path '{p}' matches forbidden pattern '{pat}'")


def assert_clean_tree(repo, log=None) -> None:
    out = run_git(["status", "--porcelain"], cwd=repo, log=log)
    if out.strip():
        raise GitError(f"target base tree is not clean: {repo}")


def _assert_git_allowed(args) -> None:
    sub = next((a for a in args if not a.startswith("-")), None)
    if sub in {"push", "remote"}:
        raise GitError(f"git '{sub}' is blocked by the harness (no-push invariant)")
    if sub == "add":
        after = args[args.index("add") + 1 :]
        flags = {a for a in after if a.startswith("-")}
        if {"-A", "--all", "-a"} & flags or "." in after:
            raise GitError("git 'add -A/--all/.' is blocked; use the explicit staging wrapper")


def run_git(
    args: list[str],
    cwd: Path,
    log: Callable[[str], None] | None = None,
    timeout: float | None = GIT_DEFAULT_TIMEOUT,
) -> str:
    _assert_git_allowed(args)
    cmd = ["git", *args]
    if log:
        log(f"git -C {cwd} {' '.join(args)}")
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        if log:
            log(f"git timed out after {timeout}s: {' '.join(args)}")
        raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from e
    if proc.returncode != 0:
        if log:
            log(f"git failed ({proc.returncode}): {' '.join(args)}")
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout
