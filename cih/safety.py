# cih/safety.py
import fnmatch
import subprocess
from pathlib import Path
from typing import Callable, Optional

class GitError(Exception):
    pass

_FORBIDDEN = [".cih/*", ".cih", ".harness/*", ".consult/*",
              "**/.cih/*", "*.pem", "*.key", "**/secrets/*"]

def forbidden_paths() -> list[str]:
    return list(_FORBIDDEN)

def validate_no_forbidden(paths: list[str], patterns: list[str]) -> None:
    for p in paths:
        for pat in patterns:
            if fnmatch.fnmatch(p, pat) or p == pat.rstrip("/*"):
                raise GitError(f"path '{p}' matches forbidden pattern '{pat}'")

def run_git(args: list[str], cwd: Path,
            log: Optional[Callable[[str], None]] = None) -> str:
    cmd = ["git", *args]
    if log:
        log(f"git -C {cwd} {' '.join(args)}")
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout
