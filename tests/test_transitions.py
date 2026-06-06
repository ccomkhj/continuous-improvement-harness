import pytest
from cih.transitions import Status, is_valid_transition, assert_transition, InvalidTransition

def test_open_can_go_in_progress():
    assert is_valid_transition(Status.OPEN, Status.IN_PROGRESS)

def test_merged_is_terminal():
    assert not is_valid_transition(Status.MERGED, Status.OPEN)
    assert not is_valid_transition(Status.MERGED, Status.IN_PROGRESS)

def test_open_to_merged_is_now_valid():
    # The ledger merges directly from `open` (selected -> applied -> merged)
    # without an intermediate `in_progress` write, so open->merged is a real
    # lifecycle edge. The previous test encoded the inverse (wrong) invariant.
    assert is_valid_transition(Status.OPEN, Status.MERGED) is True

def test_open_to_cooldown_and_expired_are_valid():
    assert is_valid_transition(Status.OPEN, Status.COOLDOWN) is True
    assert is_valid_transition(Status.OPEN, Status.EXPIRED) is True

def test_assert_transition_raises_on_invalid():
    with pytest.raises(InvalidTransition):
        assert_transition(Status.MERGED, Status.OPEN)

def test_assert_transition_passes_on_valid():
    assert_transition(Status.IN_PROGRESS, Status.MERGED)  # no raise

def test_reopen_chain_is_valid():
    assert is_valid_transition(Status.REJECTED, Status.COOLDOWN)
    assert is_valid_transition(Status.COOLDOWN, Status.OPEN)
    assert is_valid_transition(Status.DEFERRED, Status.OPEN)
    assert not is_valid_transition(Status.COOLDOWN, Status.MERGED)
