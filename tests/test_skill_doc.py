# tests/test_skill_doc.py
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "cih" / "SKILL.md"


def test_skill_doc_mentions_all_roles_and_invariants():
    text = SKILL.read_text().lower()
    for role in ["high-planner", "planner", "plan-reviewer", "executor", "execution-reviewer"]:
        assert role in text
    assert "worktree" in text
    assert "never" in text and "push" in text  # no-push invariant documented
    assert "git add -a" in text or "git add -a is" in text or "add -a" in text
