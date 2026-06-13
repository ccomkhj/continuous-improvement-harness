"""Install the interactive `cih` skill + agent definitions into a Claude Code
config directory, so `/cih` works in any repo.

pip ships only the Python package; Claude Code discovers skills/subagents from
`.claude/` on disk, so they must be copied out of the wheel explicitly.
"""

from importlib.resources import files
from pathlib import Path

from cih.roles import ROLE_NAMES

DEFAULT_DEST = Path.home() / ".claude"


def install_skill(dest=DEFAULT_DEST) -> list[Path]:
    """Copy SKILL.md and the five agent prompts under `dest`, overwriting any
    existing copies. Returns the list of files written."""
    dest = Path(dest)
    written: list[Path] = []

    skill_src = files("cih") / "_assets" / "skill" / "SKILL.md"
    skill_dst = dest / "skills" / "cih" / "SKILL.md"
    skill_dst.parent.mkdir(parents=True, exist_ok=True)
    skill_dst.write_text(skill_src.read_text())
    written.append(skill_dst)

    agents_src = files("cih") / "_assets" / "agents"
    agents_dir = dest / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for name in ROLE_NAMES:
        agent_dst = agents_dir / f"{name}.md"
        agent_dst.write_text((agents_src / f"{name}.md").read_text())
        written.append(agent_dst)

    return written
