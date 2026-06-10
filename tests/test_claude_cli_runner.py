# tests/test_claude_cli_runner.py
import json
import pytest
import cih.agents
from cih.agents import ClaudeCliRunner, _extract_json
from cih.contracts import AgentContract, OutputValidationError


def _contract():
    return AgentContract(role="planner", agent_version="1.0.0",
                         role_prompt="p", input_schema={"type": "object"},
                         output_schema={"type": "object"}, allowed_tools=[])


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch(monkeypatch, proc):
    monkeypatch.setattr(cih.agents.subprocess, "run",
                        lambda *a, **k: proc)


def test_wellformed_envelope_string_result(monkeypatch):
    _patch(monkeypatch, _FakeProc(stdout='{"result": "{\\"ok\\": true}"}'))
    out = ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"})
    assert out == {"ok": True}


def test_result_already_dict(monkeypatch):
    _patch(monkeypatch, _FakeProc(stdout='{"result": {"ok": true}}'))
    out = ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"})
    assert out == {"ok": True}


def test_non_json_stdout_raises(monkeypatch):
    _patch(monkeypatch, _FakeProc(stdout="not json"))
    with pytest.raises(RuntimeError):
        ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"})


def test_is_error_envelope_raises(monkeypatch):
    _patch(monkeypatch, _FakeProc(stdout='{"is_error": true, "result": "boom"}'))
    with pytest.raises(RuntimeError):
        ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"})


def test_nonzero_returncode_raises(monkeypatch):
    _patch(monkeypatch, _FakeProc(returncode=1, stderr="failed"))
    with pytest.raises(RuntimeError):
        ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"})


# --- regression: the high-planner crash (prose + ```json fence) ---

def test_extract_bare_json():
    assert _extract_json('{"ok": true}') == {"ok": True}


def test_extract_fenced_json():
    assert _extract_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_extract_unlabeled_fence():
    assert _extract_json('```\n{"ok": false}\n```') == {"ok": False}


def test_extract_prose_plus_fenced_json():
    text = ('Bash/Python execution is hard-denied here, so I cannot compute. '
            'Here is the audit:\n\n```json\n{"ok": true, "score": 7}\n```')
    assert _extract_json(text) == {"ok": True, "score": 7}


def test_extract_prose_then_bare_json_no_fence():
    assert _extract_json('Some preamble.\n{"ok": true}\nTrailing.') == {"ok": True}


def test_extract_nested_braces():
    text = 'prose ```json\n{"a": {"b": [1, 2]}, "ok": true}\n``` trailing'
    assert _extract_json(text) == {"a": {"b": [1, 2]}, "ok": True}


def test_extract_picks_final_fence_when_preamble_has_one():
    text = ('Example: ```json\n{"ok": false}\n```\nFinal:\n```json\n{"ok": true}\n```')
    assert _extract_json(text) == {"ok": True}


def test_extract_raises_on_pure_prose():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("no json here at all")


def test_extract_raises_typeerror_on_non_str():
    with pytest.raises(TypeError):
        _extract_json(None)


def test_clirunner_unwraps_fenced_prose_result(monkeypatch):
    # The actual crashing shape: envelope.result is a STRING that is prose +
    # a ```json fence, not bare JSON.
    inner = 'Here is the audit:\n\n```json\n{"opportunities": [], "charters": [{"id": "t1"}]}\n```'
    _patch(monkeypatch, _FakeProc(stdout=json.dumps({"result": inner})))
    out = ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"})
    assert out == {"opportunities": [], "charters": [{"id": "t1"}]}


def test_clirunner_invalid_result_raises_output_validation_error(monkeypatch):
    _patch(monkeypatch, _FakeProc(stdout=json.dumps({"result": "just chatting, no json"})))
    with pytest.raises(OutputValidationError):
        ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"})


def test_prefers_structured_output_dict(monkeypatch):
    # With --json-schema, claude returns the schema object in `structured_output`
    # and leaves `result` as a prose summary. Prefer the structured object.
    env = json.dumps({"result": "The structured output has been provided successfully.",
                      "structured_output": {"opportunities": [], "charters": [{"id": "t1"}]}})
    _patch(monkeypatch, _FakeProc(stdout=env))
    out = ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"})
    assert out == {"opportunities": [], "charters": [{"id": "t1"}]}


def test_structured_output_as_json_string(monkeypatch):
    env = json.dumps({"result": "prose", "structured_output": '{"ok": true}'})
    _patch(monkeypatch, _FakeProc(stdout=env))
    assert ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"}) == {"ok": True}


def test_falls_back_to_result_when_no_structured_output(monkeypatch):
    env = json.dumps({"result": '```json\n{"ok": true}\n```'})
    _patch(monkeypatch, _FakeProc(stdout=env))
    assert ClaudeCliRunner(cwd=".").run(_contract(), {"charter": "x"}) == {"ok": True}


def test_cmd_passes_json_schema(monkeypatch):
    captured = {}

    def _capture(cmd, *a, **k):
        captured["cmd"] = cmd
        return _FakeProc(stdout='{"result": {"ok": true}}')

    monkeypatch.setattr(cih.agents.subprocess, "run", _capture)
    schema = {"type": "object", "required": ["ok"]}
    contract = AgentContract(role="planner", agent_version="1.0.0", role_prompt="p",
                             input_schema={"type": "object"}, output_schema=schema,
                             allowed_tools=[])
    ClaudeCliRunner(cwd=".").run(contract, {"charter": "x"})
    cmd = captured["cmd"]
    assert "--json-schema" in cmd
    assert json.dumps(schema) in cmd
