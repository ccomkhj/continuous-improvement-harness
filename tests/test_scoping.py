import pytest
from cih import scoping
from cih.scoping import StubAsker, _to_choices, _ask_positive_int
from cih.config import ConfigError


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


from cih.scoping import run_scoping_interview, QuestionaryAsker


def _abs(tmp_path, name):
    p = tmp_path / name
    p.mkdir()
    return str(p)


def test_interview_fixed_n(tmp_path):
    t, s = _abs(tmp_path, "t"), _abs(tmp_path, "s")
    asker = StubAsker(["fixed-N", "3", ["tests"], "", 0.5, True])
    cfg = run_scoping_interview(t, s, asker)
    assert cfg.mode == "fixed-N"
    assert cfg.iterations == 3
    assert cfg.focus_areas == ["tests"]
    assert cfg.value_threshold == 0.5


def test_interview_until_converged_sets_max_not_iterations(tmp_path):
    t, s = _abs(tmp_path, "t"), _abs(tmp_path, "s")
    asker = StubAsker(["until-converged", "10", [], "", 0.7, True])
    cfg = run_scoping_interview(t, s, asker)
    assert cfg.mode == "until-converged"
    assert cfg.iterations is None
    assert cfg.max_iterations == 10
    assert cfg.value_threshold == 0.7


def test_interview_merges_preset_and_other_focus(tmp_path):
    t, s = _abs(tmp_path, "t"), _abs(tmp_path, "s")
    asker = StubAsker(["fixed-N", "1", ["tests", "security"], "logging, caching", 0.3, True])
    cfg = run_scoping_interview(t, s, asker)
    assert cfg.focus_areas == ["tests", "security", "logging", "caching"]


def test_interview_confirm_no_then_yes_loops_once(tmp_path):
    t, s = _abs(tmp_path, "t"), _abs(tmp_path, "s")
    asker = StubAsker([
        "fixed-N", "1", ["tests"], "", 0.5, False,
        "until-converged", "9", [], "", 0.3, True,
    ])
    cfg = run_scoping_interview(t, s, asker)
    assert cfg.mode == "until-converged"
    assert cfg.max_iterations == 9


def test_interview_validates_paths_up_front(tmp_path):
    same = _abs(tmp_path, "same")
    asker = StubAsker([])
    with pytest.raises(ConfigError):
        run_scoping_interview(same, same, asker)


class _FakeQuestion:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


def test_questionary_asker_raises_on_cancel(monkeypatch):
    asker = QuestionaryAsker()
    monkeypatch.setattr("questionary.text", lambda *a, **k: _FakeQuestion(None))
    with pytest.raises(KeyboardInterrupt):
        asker.text("anything?")


def test_questionary_asker_returns_answer(monkeypatch):
    asker = QuestionaryAsker()
    monkeypatch.setattr("questionary.confirm", lambda *a, **k: _FakeQuestion(True))
    assert asker.confirm("ok?") is True


def test_interview_summary_note_reflects_mode_and_focus(tmp_path):
    t, s = _abs(tmp_path, "t"), _abs(tmp_path, "s")
    asker = StubAsker(["fixed-N", "3", ["tests"], "", 0.5, True])
    run_scoping_interview(t, s, asker)
    summary = "\n".join(asker.notes)
    assert "iterations=3" in summary
    assert "tests" in summary


def test_interview_summary_broad_audit_when_no_focus(tmp_path):
    t, s = _abs(tmp_path, "t"), _abs(tmp_path, "s")
    asker = StubAsker(["until-converged", "5", [], "", 0.5, True])
    run_scoping_interview(t, s, asker)
    summary = "\n".join(asker.notes)
    assert "max_iterations=5" in summary
    assert "(broad audit)" in summary
