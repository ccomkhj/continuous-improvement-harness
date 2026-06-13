# tests/test_dispatch.py
from cih.dispatch import plan_dispatch, resolve_opportunity_fp
from cih.ledger import Ledger, Opportunity, fingerprint


def _opp(title="t", scope="s", value=0.9, **over):
    fields = dict(
        fp=fingerprint(title, scope),
        title=title,
        scope=scope,
        value=value,
        confidence=0.9,
        effort=0.1,
        risk=0.1,
        rationale="r",
    )
    fields.update(over)
    return Opportunity(**fields)


def _ledger(*opps):
    led = Ledger()
    for o in opps:
        led.upsert(o)
    return led


# ---- resolve_opportunity_fp ------------------------------------------------


def test_resolve_prefers_explicit_fp():
    assert resolve_opportunity_fp({"opportunity_fp": "deadbeef"}, []) == "deadbeef"


def test_resolve_by_opportunity_index():
    opps = [{"title": "a", "scope": "x"}, {"title": "b", "scope": "y"}]
    assert resolve_opportunity_fp({"opportunity_index": 1}, opps) == fingerprint("b", "y")


def test_resolve_by_inline_title_scope():
    assert resolve_opportunity_fp({"title": "c", "scope": "z"}, []) == fingerprint("c", "z")


def test_resolve_returns_none_when_unlinkable():
    assert resolve_opportunity_fp({"id": "team-01"}, []) is None
    # out-of-range index is not a link
    assert resolve_opportunity_fp({"opportunity_index": 5}, [{"title": "a", "scope": "x"}]) is None


# ---- ledger gate -----------------------------------------------------------


def test_open_opportunity_is_dispatched_and_fp_recorded():
    opp = _opp()
    led = _ledger(opp)
    plan = plan_dispatch(
        [{"id": "team-01", "opportunity_index": 0}],
        [{"title": opp.title, "scope": opp.scope}],
        led,
        value_threshold=0.5,
        current_iteration=1,
    )
    assert [c["id"] for c in plan.dispatch] == ["team-01"]
    assert plan.fp_by_team == {"team-01": opp.fp}
    assert plan.deferred == []


def test_cooldown_opportunity_is_deferred():
    opp = _opp()
    led = _ledger(opp)
    led.mark_cooldown(opp.fp, current_iteration=1, cooldown_iterations=3)  # cools until iter 4
    plan = plan_dispatch(
        [{"id": "team-01", "opportunity_fp": opp.fp}],
        [],
        led,
        value_threshold=0.5,
        current_iteration=2,
    )
    assert plan.dispatch == []
    assert [d["id"] for d in plan.deferred] == ["team-01"]
    assert "cooldown" in plan.deferred[0]["reason"]


def test_merged_opportunity_is_deferred():
    opp = _opp()
    led = _ledger(opp)
    led.mark_merged(opp.fp)
    plan = plan_dispatch(
        [{"id": "team-01", "opportunity_fp": opp.fp}],
        [],
        led,
        value_threshold=0.5,
        current_iteration=1,
    )
    assert plan.dispatch == []
    assert "merged" in plan.deferred[0]["reason"]


def test_below_threshold_opportunity_is_deferred():
    opp = _opp(value=0.2)
    led = _ledger(opp)
    plan = plan_dispatch(
        [{"id": "team-01", "opportunity_fp": opp.fp}],
        [],
        led,
        value_threshold=0.5,
        current_iteration=1,
    )
    assert plan.dispatch == []
    assert "threshold" in plan.deferred[0]["reason"]


def test_untracked_charter_always_dispatched():
    # No opportunity link at all -> can't be gated, so it runs.
    plan = plan_dispatch(
        [{"id": "team-01"}],
        [],
        Ledger(),
        value_threshold=0.5,
        current_iteration=1,
    )
    assert [c["id"] for c in plan.dispatch] == ["team-01"]
    assert plan.fp_by_team == {}


def test_fp_resolvable_but_not_in_ledger_is_dispatched():
    # A charter whose fp doesn't match any ingested opportunity can't be gated.
    plan = plan_dispatch(
        [{"id": "team-01", "opportunity_fp": "not-ingested"}],
        [],
        Ledger(),
        value_threshold=0.5,
        current_iteration=1,
    )
    assert [c["id"] for c in plan.dispatch] == ["team-01"]


# ---- file de-confliction ---------------------------------------------------


def test_file_overlap_defers_later_charter():
    charters = [
        {"id": "team-01", "impact_manifest": {"intended_files": ["a.py"]}},
        {"id": "team-02", "impact_manifest": {"intended_files": ["a.py", "b.py"]}},
        {"id": "team-03", "impact_manifest": {"intended_files": ["c.py"]}},
    ]
    plan = plan_dispatch(charters, [], Ledger(), value_threshold=0.5, current_iteration=1)
    assert [c["id"] for c in plan.dispatch] == ["team-01", "team-03"]
    assert [d["id"] for d in plan.deferred] == ["team-02"]
    assert "a.py" in plan.deferred[0]["reason"]


def test_empty_manifests_never_collide():
    charters = [{"id": f"team-{j}"} for j in range(3)]
    plan = plan_dispatch(charters, [], Ledger(), value_threshold=0.5, current_iteration=1)
    assert [c["id"] for c in plan.dispatch] == ["team-0", "team-1", "team-2"]


def test_dispatch_preserves_charter_objects_unmutated():
    charter = {"id": "team-01", "opportunity_index": 0}
    opp = _opp()
    led = _ledger(opp)
    plan = plan_dispatch(
        [charter], [{"title": opp.title, "scope": opp.scope}], led, 0.5, current_iteration=1
    )
    # the dispatched charter is the SAME object, with no injected keys
    assert plan.dispatch[0] is charter
    assert charter == {"id": "team-01", "opportunity_index": 0}
