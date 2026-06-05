# tests/test_contracts.py
import pytest
from cih.contracts import AgentContract, OutputValidationError

PLAN_OUT = {
    "type": "object",
    "required": ["tasks"],
    "properties": {"tasks": {"type": "array", "items": {"type": "string"}}},
}

def test_contract_validates_good_output():
    c = AgentContract(role="planner", agent_version="1.0.0",
                      role_prompt="Plan it.", input_schema={"type": "object"},
                      output_schema=PLAN_OUT, allowed_tools=["Read"])
    c.validate_output({"tasks": ["a", "b"]})  # no raise

def test_contract_rejects_bad_output():
    c = AgentContract(role="planner", agent_version="1.0.0",
                      role_prompt="Plan it.", input_schema={"type": "object"},
                      output_schema=PLAN_OUT, allowed_tools=["Read"])
    with pytest.raises(OutputValidationError):
        c.validate_output({"tasks": "not-a-list"})

def test_version_hash_is_stable():
    c1 = AgentContract(role="planner", agent_version="1.0.0",
                       role_prompt="Plan it.", input_schema={"type": "object"},
                       output_schema=PLAN_OUT, allowed_tools=["Read"])
    c2 = AgentContract(role="planner", agent_version="1.0.0",
                       role_prompt="Plan it.", input_schema={"type": "object"},
                       output_schema=PLAN_OUT, allowed_tools=["Read"])
    assert c1.prompt_hash() == c2.prompt_hash()

def test_hash_changes_with_allowed_tools():
    c1 = AgentContract(role="planner", agent_version="1.0.0",
                       role_prompt="Plan it.", input_schema={"type": "object"},
                       output_schema=PLAN_OUT, allowed_tools=["Read"])
    c2 = AgentContract(role="planner", agent_version="1.0.0",
                       role_prompt="Plan it.", input_schema={"type": "object"},
                       output_schema=PLAN_OUT, allowed_tools=["Read", "Edit"])
    assert c1.prompt_hash() != c2.prompt_hash()
