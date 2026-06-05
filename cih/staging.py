# cih/staging.py
from pathlib import Path
from typing import Callable, Optional
from cih.safety import run_git, forbidden_paths, validate_no_forbidden, GitError

class StagingError(Exception):
    pass

_BANNED_TOKENS = {"-A", "--all", ".", "*", ":/", ":", "-u", "--update"}

def stage_files(repo: Path, paths: list[str],
                log: Optional[Callable[[str], None]] = None) -> None:
    if not paths:
        raise StagingError("no paths declared; explicit staging requires at least one file")
    for p in paths:
        if p.strip() in _BANNED_TOKENS or p.strip().startswith("-"):
            raise StagingError(f"refusing wildcard/all-style token: {p!r}")
    try:
        validate_no_forbidden(paths, forbidden_paths())
    except GitError as e:
        raise StagingError(str(e)) from e
    # '--' terminator: everything after is a literal pathspec, never a flag
    run_git(["add", "--", *paths], cwd=repo, log=log)
