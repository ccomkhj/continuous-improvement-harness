# tests/test_conformance.py
import pytest

from cih.agents import StubRunner, invoke
from cih.roles import ROLE_NAMES, load_contracts

CANNED = {
    "high-planner": {"opportunities": [], "charters": []},
    "planner": {"tasks": ["t1"]},
    "plan-reviewer": {"approved": True, "feedback": "ok"},
    "executor": {"commits": []},
    "execution-reviewer": {"approved": True, "reasons": ["ok"]},
}


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_canned_response_is_schema_valid(role):
    contracts = load_contracts()
    runner = StubRunner(responses={role: CANNED[role]})
    out = invoke(runner, contracts[role], {"any": "input"})
    assert out == CANNED[role]


def test_bad_response_rejected_for_every_role():
    from cih.contracts import OutputValidationError
    contracts = load_contracts()
    runner = StubRunner(responses={r: {"garbage": True} for r in ROLE_NAMES})
    for role in ROLE_NAMES:
        with pytest.raises(OutputValidationError):
            invoke(runner, contracts[role], {})
