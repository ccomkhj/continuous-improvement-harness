from cih.install import install_skill
from cih.roles import ROLE_NAMES


def test_install_skill_writes_skill_and_agents(tmp_path):
    dest = tmp_path / ".claude"
    written = install_skill(dest)

    skill = dest / "skills" / "cih" / "SKILL.md"
    assert skill.is_file()
    assert "name: cih" in skill.read_text()
    assert skill in written

    for name in ROLE_NAMES:
        agent = dest / "agents" / f"{name}.md"
        assert agent.is_file()
        assert agent.read_text().strip() != ""
        assert agent in written


def test_install_skill_overwrites_existing(tmp_path):
    dest = tmp_path / ".claude"
    (dest / "agents").mkdir(parents=True)
    (dest / "agents" / "high-planner.md").write_text("stale")

    install_skill(dest)

    assert (dest / "agents" / "high-planner.md").read_text() != "stale"


def test_main_install_skill_subcommand(tmp_path):
    from cih.runner import main

    dest = tmp_path / ".claude"
    rc = main(["install-skill", "--dest", str(dest)])

    assert rc == 0
    assert (dest / "skills" / "cih" / "SKILL.md").is_file()
    assert (dest / "agents" / "high-planner.md").is_file()
