# tests/test_team.py
from cih.team import run_team, TeamResult
from cih.agents import StubRunner
from cih.contracts import AgentContract
from cih.tdd_verifier import TddVerdict

def _contracts():
    def c(role, out):
        return AgentContract(role=role, agent_version="1", role_prompt="p",
                             input_schema={"type": "object"}, output_schema=out)
    return {
        "planner": c("planner", {"type": "object", "required": ["tasks"],
                                 "properties": {"tasks": {"type": "array"}}}),
        "plan-reviewer": c("plan-reviewer", {"type": "object",
            "required": ["approved", "feedback"],
            "properties": {"approved": {"type": "boolean"},
                           "feedback": {"type": "string"}}}),
        "executor": c("executor", {"type": "object", "required": ["commits"],
                                   "properties": {"commits": {"type": "array"}}}),
        "execution-reviewer": c("execution-reviewer", {"type": "object",
            "required": ["approved", "reasons"],
            "properties": {"approved": {"type": "boolean"},
                           "reasons": {"type": "array"}}}),
    }

def _green_verifier(**kwargs):
    return TddVerdict(eligible=True, passed=True, red_failed=True,
                      green_passed=True, full_suite_passed=True)

def test_happy_path_team_passes():
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": [{"task": "t1", "red_sha": "r", "green_sha": "g",
                                  "test_command": ["pytest"], "declared_test_paths": ["t.py"]}]},
        "execution-reviewer": {"approved": True, "reasons": ["ok"]},
    })
    result = run_team(charter={"id": "team-01", "goal": "x"}, contracts=_contracts(),
                      runner=runner, verifier=_green_verifier,
                      plan_review_retries=2, exec_review_retries=2, attempt_cap=4)
    assert isinstance(result, TeamResult)
    assert result.passed

def test_team_fails_when_tdd_verifier_blocks():
    def red_verifier(**kwargs):
        return TddVerdict(eligible=True, passed=False, reason="red commit did not fail")
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": [{"task": "t1", "red_sha": "r", "green_sha": "g",
                                  "test_command": ["pytest"], "declared_test_paths": ["t.py"]}]},
        "execution-reviewer": {"approved": True, "reasons": ["ok"]},
    })
    result = run_team(charter={"id": "team-01", "goal": "x"}, contracts=_contracts(),
                      runner=runner, verifier=red_verifier,
                      plan_review_retries=1, exec_review_retries=1, attempt_cap=4)
    assert not result.passed
    assert "tdd" in result.reason.lower()

def test_plan_rejection_triggers_replan_then_gives_up():
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": False, "feedback": "too vague"},
        "executor": {"commits": []},
        "execution-reviewer": {"approved": True, "reasons": []},
    })
    result = run_team(charter={"id": "team-01", "goal": "x"}, contracts=_contracts(),
                      runner=runner, verifier=_green_verifier,
                      plan_review_retries=2, exec_review_retries=2, attempt_cap=10)
    assert not result.passed
    assert "plan" in result.reason.lower()

def test_attempt_cap_exceeded_returns_failed():
    # Plan passes review (consumes the only attempt slot), then the first
    # EXECUTION attempt.start raises AttemptCapExceeded -> team fails.
    runner = StubRunner(responses={
        "planner": {"tasks": ["t1"]},
        "plan-reviewer": {"approved": True, "feedback": ""},
        "executor": {"commits": [{"task": "t1", "red_sha": "r", "green_sha": "g",
                                  "test_command": ["pytest"], "declared_test_paths": ["t.py"]}]},
        "execution-reviewer": {"approved": True, "reasons": ["ok"]},
    })
    result = run_team(charter={"id": "team-01", "goal": "x"}, contracts=_contracts(),
                      runner=runner, verifier=_green_verifier,
                      plan_review_retries=2, exec_review_retries=2, attempt_cap=1)
    assert not result.passed
    assert result.reason == "attempt cap exceeded"
