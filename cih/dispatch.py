# cih/dispatch.py
"""Charter dispatch coordination — how the orchestrator steers the team.

Between the high-planner audit and the team runner, the orchestrator must
decide WHICH of the proposed charters to actually dispatch this iteration.
Three concerns live here so the orchestrator loop stays a thin control flow:

1. ``resolve_opportunity_fp`` — link each charter to its ledger opportunity.
   The high-planner is forbidden from computing fingerprints (the harness owns
   them), so a charter points at its opportunity by, in priority order: an
   explicit ``opportunity_fp`` (already resolved), an ``opportunity_index``
   into the audit's ``opportunities`` array, or inline ``title``/``scope``.
   Resolving here is what makes ledger marking — and therefore cooldown,
   expiry, and convergence — actually fire on a real run.

2. ledger gate — defer a charter whose opportunity is not currently actionable
   (cooling down, expired, already merged, or below the value threshold).
   Without this, a re-proposed cooled-down opportunity still gets a full
   five-stage team run, wasting budget and defeating the cooldown.

3. file gate — charters are meant to touch disjoint files; when two in the same
   batch declare overlapping ``intended_files`` only the first is dispatched and
   the rest are deferred, so teams never collide with each other at merge.

Charters are never mutated: the resolved fingerprints are returned alongside
the (sub)list of charters to dispatch, so observability artifacts persist the
exact charter objects the high-planner emitted.
"""

from dataclasses import dataclass, field

from cih.ledger import Ledger, fingerprint


@dataclass
class DispatchPlan:
    dispatch: list = field(default_factory=list)  # charters to run, in order
    fp_by_team: dict = field(default_factory=dict)  # team_id -> opportunity_fp (resolvable only)
    deferred: list = field(default_factory=list)  # [{"id", "reason"}] skipped this iteration


def resolve_opportunity_fp(charter: dict, opportunities: list) -> str | None:
    """Return the ledger fingerprint a charter targets, or None if unlinkable.

    Tried most-specific first: an explicit ``opportunity_fp``; an
    ``opportunity_index`` into ``opportunities``; inline ``title``+``scope``.
    A charter with no resolvable link is "untracked" — it cannot be gated by
    the ledger and is always eligible to dispatch.
    """
    fp = charter.get("opportunity_fp")
    if fp:
        return fp
    idx = charter.get("opportunity_index")
    if isinstance(idx, int) and 0 <= idx < len(opportunities):
        opp = opportunities[idx]
        return fingerprint(opp["title"], opp["scope"])
    title, scope = charter.get("title"), charter.get("scope")
    if title and scope:
        return fingerprint(title, scope)
    return None


def _intended_files(charter: dict) -> set[str]:
    files = charter.get("impact_manifest", {}).get("intended_files", []) or []
    return {f for f in files if f}


def _gate_reason(ledger: Ledger, fp: str, value_threshold: float) -> str:
    o = ledger.get(fp)
    if o is not None and o.state != "open":
        return f"opportunity {o.state}"
    return f"value below threshold ({value_threshold})"


def plan_dispatch(
    charters: list,
    opportunities: list,
    ledger: Ledger,
    value_threshold: float,
    current_iteration: int,
) -> DispatchPlan:
    """Decide which charters to dispatch this iteration (see module docstring).

    Charters are considered in the high-planner's order so its ranking is
    honored. ``select_open`` is called once up front: it refreshes elapsed
    cooldowns (reopening them) before computing the actionable set.
    """
    actionable = {o.fp for o in ledger.select_open(value_threshold, current_iteration)}
    plan = DispatchPlan()
    claimed: set[str] = set()
    for charter in charters:
        cid = charter.get("id")
        fp = resolve_opportunity_fp(charter, opportunities)

        # ledger gate: only gate charters whose opportunity the ledger tracks.
        if fp is not None and ledger.get(fp) is not None and fp not in actionable:
            plan.deferred.append({"id": cid, "reason": _gate_reason(ledger, fp, value_threshold)})
            continue

        # file gate: defer a charter that overlaps files an earlier one claimed.
        files = _intended_files(charter)
        overlap = files & claimed
        if overlap:
            plan.deferred.append(
                {"id": cid, "reason": f"file overlap with earlier charter: {sorted(overlap)}"}
            )
            continue

        plan.dispatch.append(charter)
        claimed |= files
        if fp is not None:
            plan.fp_by_team[cid] = fp
    return plan
