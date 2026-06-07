from importlib.resources import files

from cih.roles import load_contracts, ROLE_NAMES


def test_agent_prompts_are_packaged_resources():
    """Prompts ship inside the wheel so the pip-installed CLI works with no
    repo-level .claude/ directory present."""
    base = files("cih") / "_assets" / "agents"
    for name in ROLE_NAMES:
        assert (base / f"{name}.md").is_file()


def test_skill_md_is_packaged_resource():
    assert (files("cih") / "_assets" / "skill" / "SKILL.md").is_file()


def test_load_contracts_uses_packaged_prompts():
    """load_contracts() resolves prompts from package data, not from a path
    relative to the repo checkout."""
    contracts = load_contracts()
    assert set(contracts) == set(ROLE_NAMES)
    for c in contracts.values():
        assert len(c.role_prompt.strip()) > 20
