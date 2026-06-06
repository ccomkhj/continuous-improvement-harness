"""Append-only progress sink owned by the orchestrator (spec §10/§11).

`<state_dir>/progress.md` is the audit trail: every git command run via
`run_git(..., log=...)` is recorded here, so the harness can prove the
safety/audit invariant that "every git command is logged."
"""
from pathlib import Path

from cih.state import _now


def append_progress(state_dir, line: str) -> None:
    p = Path(state_dir) / "progress.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"{_now()} {line}\n")
