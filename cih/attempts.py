from dataclasses import asdict, dataclass
from enum import Enum


class AttemptKind(str, Enum):
    PLAN = "plan_retry"
    EXECUTION = "execution_retry"
    INTEGRATION = "integration_retry"
    FINAL_REJECT = "final_reject"

class AttemptCapExceeded(Exception):
    pass

@dataclass
class Attempt:
    attempt_id: str
    kind: str
    base_sha: str
    branch: str
    worktree_path: str
    feedback_input: str
    parent_attempt_id: str | None = None
    is_current: bool = True

class AttemptLog:
    def __init__(self, team_id: str, cap: int):
        self.team_id = team_id
        self.cap = cap
        self._attempts: list[Attempt] = []

    def start(self, kind: AttemptKind, base_sha: str, branch: str,
              worktree_path: str, feedback: str,
              parent: str | None = None) -> Attempt:
        if len(self._attempts) >= self.cap:
            raise AttemptCapExceeded(
                f"{self.team_id}: attempt cap {self.cap} reached")
        for a in self._attempts:
            a.is_current = False
        att = Attempt(
            attempt_id=f"attempt-{len(self._attempts)+1:02d}",
            kind=kind.value if isinstance(kind, AttemptKind) else kind,
            base_sha=base_sha, branch=branch, worktree_path=worktree_path,
            feedback_input=feedback, parent_attempt_id=parent)
        self._attempts.append(att)
        return att

    def current(self) -> Attempt | None:
        return self._attempts[-1] if self._attempts else None

    def all(self) -> list[Attempt]:
        return list(self._attempts)

    def to_dict(self) -> dict:
        return {"team_id": self.team_id, "cap": self.cap,
                "attempts": [asdict(a) for a in self._attempts]}

    @classmethod
    def from_dict(cls, d: dict) -> "AttemptLog":
        log = cls(team_id=d["team_id"], cap=d["cap"])
        log._attempts = [Attempt(**a) for a in d["attempts"]]
        return log
