# tests/test_claude_cli_runner.py
import pytest
import cih.agents
from cih.agents import ClaudeCliRunner
from cih.contracts import AgentContract


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
