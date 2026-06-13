# tests/test_agents.py
import pytest

from cih.agents import StubRunner, invoke
from cih.contracts import AgentContract, OutputValidationError

OUT = {"type": "object", "required": ["ok"],
       "properties": {"ok": {"type": "boolean"}}}

def _contract():
    return AgentContract(role="planner", agent_version="1.0.0",
                         role_prompt="p", input_schema={"type": "object"},
                         output_schema=OUT, allowed_tools=[])

def test_invoke_returns_validated_output():
    runner = StubRunner(responses={"planner": {"ok": True}})
    out = invoke(runner, _contract(), {"charter": "x"})
    assert out == {"ok": True}

def test_invoke_raises_on_schema_violation():
    runner = StubRunner(responses={"planner": {"ok": "nope"}})
    with pytest.raises(OutputValidationError):
        invoke(runner, _contract(), {"charter": "x"})

def test_stub_records_calls():
    runner = StubRunner(responses={"planner": {"ok": True}})
    invoke(runner, _contract(), {"charter": "x"})
    assert runner.calls[0]["role"] == "planner"
    assert runner.calls[0]["input"] == {"charter": "x"}
