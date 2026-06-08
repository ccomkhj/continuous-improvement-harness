import pytest
from cih import scoping
from cih.scoping import StubAsker, _to_choices


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
