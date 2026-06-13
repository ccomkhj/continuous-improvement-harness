# cih/staging.py
import os
from collections.abc import Callable
from pathlib import Path

from cih.safety import GitError, forbidden_paths, run_git, validate_no_forbidden


class StagingError(Exception):
    pass

# Glob metacharacters that would let git expand a single declared pathspec
# into many files. We use an allowlist of literal paths instead of a denylist.
_GLOB_CHARS = ("*", "?", "[")

def _staged_set(repo: Path) -> set:
    out = run_git(["diff", "--cached", "--name-only"], cwd=repo)
    return set(out.split())

def stage_files(repo: Path, paths: list[str],
                log: Callable[[str], None] | None = None) -> None:
    if not paths:
        raise StagingError("no paths declared; explicit staging requires at least one file")

    cleaned: list[str] = []
    for raw in paths:
        p = raw.strip()
        if p == "":
            raise StagingError(f"refusing empty pathspec: {raw!r}")
        if p in (".", "./"):
            raise StagingError(f"refusing whole-tree pathspec: {raw!r}")
        if p.startswith("-"):
            raise StagingError(f"refusing flag-style token: {raw!r}")
        if os.path.isabs(p):
            raise StagingError(f"refusing absolute path: {raw!r}")
        if ":" in p:
            # git magic pathspec prefix, e.g. ':(glob)', ':(top)', ':/'
            raise StagingError(f"refusing git magic pathspec: {raw!r}")
        if any(c in p for c in _GLOB_CHARS):
            raise StagingError(f"refusing glob metacharacter in pathspec: {raw!r}")
        if ".." in p.replace(os.sep, "/").split("/"):
            raise StagingError(f"refusing '..' traversal segment in pathspec: {raw!r}")
        cleaned.append(p)

    try:
        validate_no_forbidden(cleaned, forbidden_paths())
    except GitError as e:
        raise StagingError(str(e)) from e

    # Allowlist of expected results: the normalized declared paths.
    declared = {os.path.normpath(p).replace(os.sep, "/") for p in cleaned}

    # Snapshot what was already staged, stage, then verify the delta is a
    # subset of what we declared. This post-stage subset check — not the
    # token rejection above — is the actual structural guarantee.
    before = _staged_set(repo)
    # '--' terminator: everything after is a literal pathspec, never a flag.
    run_git(["add", "--", *cleaned], cwd=repo, log=log)
    after = _staged_set(repo)
    newly = after - before

    unexpected = {n for n in newly if os.path.normpath(n).replace(os.sep, "/") not in declared}
    if unexpected:
        # undo only the unexpected entries; leave any legitimately-declared ones
        run_git(["reset", "-q", "--", *sorted(unexpected)], cwd=repo, log=log)
        raise StagingError(
            f"staging produced unexpected pathspec(s): {sorted(unexpected)}")
