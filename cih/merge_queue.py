# cih/merge_queue.py
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class MergeOutcome:
    merged: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    final_base_sha: str = ""

def order_by_overlap(charters: list[dict]) -> list[dict]:
    # cheap precheck: fewer intended files -> integrate earlier (less collision surface)
    return sorted(charters,
                  key=lambda c: len(c.get("impact_manifest", {}).get("intended_files", [])))

def integrate(teams: list[tuple], base_sha: str, reverify: Callable[[str, str], bool],
              integration_retries: int) -> MergeOutcome:
    """teams: list of (team_id, charter). reverify(team_id, base)->bool re-runs the
    full suite + execution-reviewer on the rebased branch."""
    ordered_ids = [c["id"] for c in order_by_overlap([c for _, c in teams])]
    by_id = dict(teams)
    outcome = MergeOutcome(final_base_sha=base_sha)
    for team_id in ordered_ids:
        passed = False
        for _ in range(integration_retries + 1):
            if reverify(team_id, outcome.final_base_sha):
                passed = True
                break
        if passed:
            outcome.merged.append(team_id)
            outcome.final_base_sha = f"{outcome.final_base_sha}+{team_id}"
        else:
            outcome.rejected.append(team_id)
    return outcome
