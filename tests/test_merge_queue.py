# tests/test_merge_queue.py
from cih.merge_queue import MergeOutcome, integrate, order_by_overlap


def _charter(cid, files):
    return {"id": cid, "impact_manifest": {"intended_files": files}}

def test_order_puts_low_overlap_first():
    charters = [_charter("a", ["x.py", "y.py"]), _charter("b", ["z.py"])]
    ordered = order_by_overlap(charters)
    assert ordered[0]["id"] == "b"  # fewer files / less overlap risk first

def test_integrate_merges_all_when_reverify_passes():
    teams = [("a", _charter("a", ["x.py"])), ("b", _charter("b", ["y.py"]))]
    log = []
    def reverify(team_id, base):  # always green, returns real new base sha
        log.append(team_id); return (True, base + "-" + team_id)
    outcome = integrate(teams, base_sha="base", reverify=reverify,
                        integration_retries=2)
    assert isinstance(outcome, MergeOutcome)
    assert outcome.merged == ["a", "b"]
    assert outcome.rejected == []
    # final_base_sha reflects the real SHA returned by reverify, chained across teams
    assert outcome.final_base_sha == "base-a-b"

def test_integrate_rejects_after_retry_budget():
    teams = [("a", _charter("a", ["x.py"]))]
    calls = {"n": 0}
    def reverify(team_id, base):
        calls["n"] += 1
        return (False, None)  # never passes
    outcome = integrate(teams, base_sha="base", reverify=reverify,
                        integration_retries=2)
    assert outcome.merged == []
    assert outcome.rejected == ["a"]
    assert outcome.final_base_sha == "base"  # unchanged on reject
    assert calls["n"] == 3  # initial + 2 retries, bounded
