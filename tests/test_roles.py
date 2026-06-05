# tests/test_roles.py
from cih.roles import load_contracts, ROLE_NAMES

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
