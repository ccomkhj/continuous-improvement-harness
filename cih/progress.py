"""Append-only progress sink owned by the orchestrator (spec §10/§11).

`<state_dir>/progress.md` is the audit trail: every git command run via
`run_git(..., log=...)` is recorded here, so the harness can prove the
safety/audit invariant that "every git command is logged."
"""

import os
import shlex
import subprocess
from pathlib import Path

from cih.state import _now


def append_progress(state_dir, line: str) -> None:
    p = Path(state_dir) / "progress.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"{_now()} {line}\n")


# A misbehaving notifier must never stall the loop; bound it tightly.
NOTIFY_DEFAULT_TIMEOUT = 10.0


def notify(state_dir, line: str, timeout: float | None = NOTIFY_DEFAULT_TIMEOUT) -> None:
    """Record a milestone to progress.md AND push it to an optional notifier.

    Always appends (so the watcher/audit trail is unchanged). If the env var
    `CIH_NOTIFY_CMD` is set, runs it with the milestone line appended as the
    final argument — e.g. `CIH_NOTIFY_CMD="terminal-notifier -title cih -message"`
    or a wrapper that calls osascript / posts to Slack. Best-effort and bounded
    by `timeout`: a missing, failing, or hanging notifier never aborts the run.
    """
    append_progress(state_dir, line)
    cmd = os.environ.get("CIH_NOTIFY_CMD")
    if not cmd:
        return
    try:
        subprocess.run(
            [*shlex.split(cmd), line],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except Exception:
        pass  # notifications are best-effort; never break the loop
