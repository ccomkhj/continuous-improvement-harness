import pytest
from cih.transitions import Status, is_valid_transition, assert_transition, InvalidTransition

def test_open_can_go_in_progress():
    assert is_valid_transition(Status.OPEN, Status.IN_PROGRESS)

def test_merged_is_terminal():
    assert not is_valid_transition(Status.MERGED, Status.OPEN)
    assert not is_valid_transition(Status.MERGED, Status.IN_PROGRESS)

def test_cannot_skip_from_open_to_merged():
    assert not is_valid_transition(Status.OPEN, Status.MERGED)

def test_assert_transition_raises_on_invalid():
    with pytest.raises(InvalidTransition):
        assert_transition(Status.MERGED, Status.OPEN)

def test_assert_transition_passes_on_valid():
    assert_transition(Status.IN_PROGRESS, Status.MERGED)  # no raise
