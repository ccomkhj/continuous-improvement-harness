import pytest
from cih import scoping
from cih.scoping import StubAsker, _to_choices, _ask_positive_int


def test_to_choices_maps_label_value_pairs():
    pairs = [("Fixed", "fixed-N"), ("Converge", "until-converged")]
    choices = _to_choices(pairs)
    assert [c.title for c in choices] == ["Fixed", "Converge"]
    assert [c.value for c in choices] == ["fixed-N", "until-converged"]


def test_stub_asker_returns_scripted_answers_in_order():
    asker = StubAsker(["a", ["x", "y"], "tail", True])
    assert asker.select("m?", [("A", "a")]) == "a"
    assert asker.checkbox("m?", [("X", "x")]) == ["x", "y"]
    assert asker.text("m?", default="d") == "tail"
    assert asker.confirm("ok?") is True


def test_stub_asker_records_notes_without_consuming_answers():
    asker = StubAsker(["only"])
    asker.note("hello")
    asker.note("world")
    assert asker.notes == ["hello", "world"]
    assert asker.select("m?", []) == "only"


def test_ask_positive_int_accepts_valid():
    asker = StubAsker(["3"])
    assert _ask_positive_int(asker, "n?", 5) == 3


def test_ask_positive_int_reasks_on_non_numeric_then_accepts():
    asker = StubAsker(["abc", "4"])
    assert _ask_positive_int(asker, "n?", 5) == 4
    assert any("whole number" in n for n in asker.notes)


def test_ask_positive_int_reasks_on_zero_or_negative():
    asker = StubAsker(["0", "-2", "7"])
    assert _ask_positive_int(asker, "n?", 5) == 7
    assert any("positive" in n for n in asker.notes)
