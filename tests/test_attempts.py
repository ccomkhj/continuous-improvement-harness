import pytest

from cih.attempts import AttemptCapExceeded, AttemptKind, AttemptLog


def test_records_attempts_and_marks_current():
    log = AttemptLog(team_id="team-01", cap=4)
    a1 = log.start(
        kind=AttemptKind.EXECUTION,
        base_sha="aaa",
        branch="cih/r/team-01",
        worktree_path="/wt",
        feedback="",
    )
    assert log.current().attempt_id == a1.attempt_id
    a2 = log.start(
        kind=AttemptKind.PLAN,
        base_sha="aaa",
        branch="cih/r/team-01",
        worktree_path="/wt",
        feedback="reviewer said scope wrong",
        parent=a1.attempt_id,
    )
    assert log.current().attempt_id == a2.attempt_id
    assert a2.parent_attempt_id == a1.attempt_id
    assert len(log.all()) == 2  # failed attempts preserved


def test_cap_enforced_across_all_kinds():
    log = AttemptLog(team_id="team-01", cap=2)
    log.start(kind=AttemptKind.EXECUTION, base_sha="a", branch="b", worktree_path="/w", feedback="")
    log.start(
        kind=AttemptKind.INTEGRATION, base_sha="a", branch="b", worktree_path="/w", feedback=""
    )
    with pytest.raises(AttemptCapExceeded):
        log.start(
            kind=AttemptKind.EXECUTION, base_sha="a", branch="b", worktree_path="/w", feedback=""
        )


def test_serialization_roundtrip():
    log = AttemptLog(team_id="team-01", cap=4)
    log.start(kind=AttemptKind.EXECUTION, base_sha="a", branch="b", worktree_path="/w", feedback="")
    restored = AttemptLog.from_dict(log.to_dict())
    assert restored.current().base_sha == "a"
    assert restored.cap == 4
