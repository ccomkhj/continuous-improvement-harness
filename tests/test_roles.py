# tests/test_roles.py
import pytest
from cih.roles import load_contracts, ROLE_NAMES
from cih.agents import StubRunner, invoke
from cih.contracts import OutputValidationError

def test_all_roles_load_with_prompt_bodies():
    contracts = load_contracts()
    assert set(contracts) == set(ROLE_NAMES)
    for name, c in contracts.items():
        assert c.role == name
        assert len(c.role_prompt.strip()) > 20      # real prompt body present
        assert c.output_schema["type"] == "object"

def test_planner_output_schema_requires_tasks():
    c = load_contracts()["planner"]
    assert "tasks" in c.output_schema["required"]

def test_executor_schema_rejects_unstructured_commits():
    c = load_contracts()["executor"]
    runner = StubRunner(responses={"executor": {"commits": ["garbage"]}})
    with pytest.raises(OutputValidationError):
        invoke(runner, c, {})

def test_executor_schema_accepts_wellformed_commits():
    c = load_contracts()["executor"]
    good = {"commits": [{"task": "t1", "red_sha": "r", "green_sha": "g",
                         "test_command": ["pytest"], "declared_test_paths": ["t.py"]}]}
    runner = StubRunner(responses={"executor": good})
    assert invoke(runner, c, {}) == good
