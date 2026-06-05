# cih/team.py
from dataclasses import dataclass, field
from typing import Callable
from cih.agents import invoke
from cih.attempts import AttemptLog, AttemptKind, AttemptCapExceeded

@dataclass
class TeamResult:
    team_id: str
    passed: bool
    reason: str = ""
    plan: dict = field(default_factory=dict)
    commits: list = field(default_factory=list)
    tdd_verdicts: list = field(default_factory=list)
    attempts: list = field(default_factory=list)

def run_team(charter: dict, contracts: dict, runner, verifier: Callable,
             plan_review_retries: int, exec_review_retries: int,
             attempt_cap: int, base_sha: str = "", branch: str = "",
             worktree_path: str = "") -> TeamResult:
    team_id = charter["id"]
    attempts = AttemptLog(team_id=team_id, cap=attempt_cap)

    def _finish(result: TeamResult) -> TeamResult:
        result.attempts = [a.__dict__ for a in attempts.all()]
        return result

    # plan + plan-review loop
    plan, feedback = None, ""
    approved = False
    for _ in range(plan_review_retries + 1):
        try:
            attempts.start(AttemptKind.PLAN, base_sha=base_sha, branch=branch,
                           worktree_path=worktree_path, feedback=feedback)
        except AttemptCapExceeded:
            return _finish(TeamResult(team_id, False, "attempt cap exceeded", plan=plan))
        plan = invoke(runner, contracts["planner"],
                      {"charter": charter, "feedback": feedback})
        review = invoke(runner, contracts["plan-reviewer"],
                        {"charter": charter, "plan": plan})
        if review["approved"]:
            approved = True
            break
        feedback = review["feedback"]
    if not approved:
        return _finish(TeamResult(team_id, False,
                                  "plan never approved by plan-reviewer", plan=plan))

    # execute + verify + execution-review loop
    reason = "exec never approved"
    for _ in range(exec_review_retries + 1):
        try:
            attempts.start(AttemptKind.EXECUTION, base_sha=base_sha, branch=branch,
                           worktree_path=worktree_path, feedback=reason)
        except AttemptCapExceeded:
            return _finish(TeamResult(team_id, False, "attempt cap exceeded", plan=plan))
        execution = invoke(runner, contracts["executor"],
                           {"charter": charter, "plan": plan})
        commits = execution["commits"]
        # call the verifier with ONLY its declared params (commit dicts also carry "task")
        verdicts = [verifier(red_sha=c["red_sha"], green_sha=c["green_sha"],
                             test_command=c["test_command"],
                             declared_test_paths=c["declared_test_paths"])
                    for c in commits] if commits else []
        if any(v.eligible and not v.passed for v in verdicts):
            bad = next(v for v in verdicts if v.eligible and not v.passed)
            reason = f"tdd verifier blocked: {bad.reason}"
            continue
        suspicious = any(getattr(v, "suspicious_assertions", False) for v in verdicts)
        review = invoke(runner, contracts["execution-reviewer"],
                        {"charter": charter, "plan": plan, "commits": commits,
                         "tdd_verdicts": [v.__dict__ for v in verdicts],
                         "suspicious_assertions": suspicious})
        if review["approved"]:
            return _finish(TeamResult(team_id, True, "passed", plan=plan,
                                      commits=commits, tdd_verdicts=verdicts))
        reason = "execution-reviewer rejected: " + "; ".join(review["reasons"])
    return _finish(TeamResult(team_id, False, reason, plan=plan))
