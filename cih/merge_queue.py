# cih/merge_queue.py
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class MergeOutcome:
    merged: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    final_base_sha: str = ""

def order_by_overlap(charters: list[dict]) -> list[dict]:
    # cheap precheck: fewer intended files -> integrate earlier (less collision surface)
    return sorted(charters,
                  key=lambda c: len(c.get("impact_manifest", {}).get("intended_files", [])))

def integrate(teams: list[tuple], base_sha: str,
              reverify: Callable[[str, str], tuple[bool, str | None]],
              integration_retries: int) -> MergeOutcome:
    """teams: list of (team_id, charter). reverify(team_id, base)->(ok, new_base_sha)
    re-runs the full suite + execution-reviewer on the rebased branch and returns
    the real new base SHA on success."""
    ordered_ids = [c["id"] for c in order_by_overlap([c for _, c in teams])]
    outcome = MergeOutcome(final_base_sha=base_sha)
    for team_id in ordered_ids:
        new_base_sha = None
        for _ in range(integration_retries + 1):
            ok, candidate = reverify(team_id, outcome.final_base_sha)
            if ok:
                new_base_sha = candidate
                break
        if new_base_sha is not None:
            outcome.merged.append(team_id)
            outcome.final_base_sha = new_base_sha
        else:
            outcome.rejected.append(team_id)
    return outcome
