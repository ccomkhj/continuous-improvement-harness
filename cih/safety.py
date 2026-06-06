# cih/safety.py
import fnmatch
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

class GitError(Exception):
    pass

_FORBIDDEN = [".cih/*", ".cih", ".harness/*", ".consult/*",
              "**/.cih/*", "*.pem", "*.key",
              "secrets/*", "secrets", "**/secrets/*"]

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

def run_git(args: list[str], cwd: Path,
            log: Optional[Callable[[str], None]] = None) -> str:
    cmd = ["git", *args]
    if log:
        log(f"git -C {cwd} {' '.join(args)}")
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        if log:
            log(f"git failed ({proc.returncode}): {' '.join(args)}")
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout
