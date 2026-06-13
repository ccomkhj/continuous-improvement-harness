# tests/test_ledger.py
import pytest

from cih.ledger import Ledger, Opportunity, fingerprint
from cih.transitions import InvalidTransition


def test_fingerprint_is_stable_and_normalized():
    a = fingerprint("Improve  Test Coverage", "src/foo.py")
    b = fingerprint("improve test coverage", "src/foo.py")
    assert a == b


def test_add_and_select_above_threshold():
    led = Ledger()
    led.upsert(
        Opportunity(
            fp=fingerprint("a", "x"),
            title="a",
            scope="x",
            value=0.9,
            confidence=0.8,
            effort=0.2,
            risk=0.1,
            rationale="high value",
        )
    )
    led.upsert(
        Opportunity(
            fp=fingerprint("b", "y"),
            title="b",
            scope="y",
            value=0.2,
            confidence=0.5,
            effort=0.5,
            risk=0.5,
            rationale="low value",
        )
    )
    selected = led.select_open(value_threshold=0.5)
    assert [o.title for o in selected] == ["a"]


def test_dry_when_no_open_above_threshold_and_none_retryable():
    led = Ledger()
    led.upsert(
        Opportunity(
            fp="f1",
            title="t",
            scope="s",
            value=0.1,
            confidence=0.1,
            effort=0.1,
            risk=0.1,
            rationale="r",
        )
    )
    assert led.is_dry(value_threshold=0.5, current_iteration=5)


def test_item_in_cooldown_does_not_block_dryness():
    led = Ledger()
    o = Opportunity(
        fp="f", title="t", scope="s", value=0.9, confidence=0.9, effort=0.1, risk=0.1, rationale="r"
    )
    led.upsert(o)
    led.mark_cooldown("f", current_iteration=1, cooldown_iterations=5)
    # inside cooldown -> excluded from open -> dry
    assert led.is_dry(0.5, current_iteration=2) is True
    # after cooldown -> reopened -> not dry
    assert led.is_dry(0.5, current_iteration=6) is False


def test_cooldown_blocks_reselection_until_expired(monkeypatch):
    led = Ledger()
    o = Opportunity(
        fp="f", title="t", scope="s", value=0.9, confidence=0.9, effort=0.1, risk=0.1, rationale="r"
    )
    led.upsert(o)
    led.mark_cooldown("f", current_iteration=1, cooldown_iterations=2)
    # within cooldown -> not selectable, not dry-blocking-clear
    assert led.select_open(value_threshold=0.5, current_iteration=2) == []
    # after cooldown -> reopened and selectable
    assert [x.title for x in led.select_open(value_threshold=0.5, current_iteration=3)] == ["t"]


def test_ledger_rejects_illegal_state_jump():
    led = Ledger()
    # Already in a terminal state; any lifecycle mutation is an illegal jump.
    led.upsert(
        Opportunity(
            fp="f",
            title="t",
            scope="s",
            value=0.9,
            confidence=0.9,
            effort=0.1,
            risk=0.1,
            rationale="r",
            state="merged",
        )
    )
    with pytest.raises(InvalidTransition):
        led.mark_cooldown("f", current_iteration=1, cooldown_iterations=1)


def test_expires_after_max_attempts():
    led = Ledger()
    o = Opportunity(
        fp="f", title="t", scope="s", value=0.9, confidence=0.9, effort=0.1, risk=0.1, rationale="r"
    )
    led.upsert(o)
    for i in range(3):
        led.record_attempt_failure("f", current_iteration=i, cooldown_iterations=0, max_attempts=3)
    assert led.get("f").state == "expired"
    assert led.select_open(value_threshold=0.5, current_iteration=99) == []
