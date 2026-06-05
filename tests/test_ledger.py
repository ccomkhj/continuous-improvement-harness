# tests/test_ledger.py
from cih.ledger import Ledger, Opportunity, fingerprint

def test_fingerprint_is_stable_and_normalized():
    a = fingerprint("Improve  Test Coverage", "src/foo.py")
    b = fingerprint("improve test coverage", "src/foo.py")
    assert a == b

def test_add_and_select_above_threshold():
    led = Ledger()
    led.upsert(Opportunity(fp=fingerprint("a", "x"), title="a", scope="x",
                           value=0.9, confidence=0.8, effort=0.2, risk=0.1,
                           rationale="high value"))
    led.upsert(Opportunity(fp=fingerprint("b", "y"), title="b", scope="y",
                           value=0.2, confidence=0.5, effort=0.5, risk=0.5,
                           rationale="low value"))
    selected = led.select_open(value_threshold=0.5)
    assert [o.title for o in selected] == ["a"]

def test_dry_when_no_open_above_threshold_and_none_retryable():
    led = Ledger()
    led.upsert(Opportunity(fp="f1", title="t", scope="s", value=0.1,
                           confidence=0.1, effort=0.1, risk=0.1, rationale="r"))
    assert led.is_dry(value_threshold=0.5, current_iteration=5)

def test_cooldown_blocks_reselection_until_expired(monkeypatch):
    led = Ledger()
    o = Opportunity(fp="f", title="t", scope="s", value=0.9, confidence=0.9,
                    effort=0.1, risk=0.1, rationale="r")
    led.upsert(o)
    led.mark_cooldown("f", current_iteration=1, cooldown_iterations=2)
    # within cooldown -> not selectable, not dry-blocking-clear
    assert led.select_open(value_threshold=0.5, current_iteration=2) == []
    # after cooldown -> reopened and selectable
    assert [x.title for x in led.select_open(value_threshold=0.5, current_iteration=3)] == ["t"]

def test_expires_after_max_attempts():
    led = Ledger()
    o = Opportunity(fp="f", title="t", scope="s", value=0.9, confidence=0.9,
                    effort=0.1, risk=0.1, rationale="r")
    led.upsert(o)
    for i in range(3):
        led.record_attempt_failure("f", current_iteration=i,
                                    cooldown_iterations=0, max_attempts=3)
    assert led.get("f").state == "expired"
    assert led.select_open(value_threshold=0.5, current_iteration=99) == []
