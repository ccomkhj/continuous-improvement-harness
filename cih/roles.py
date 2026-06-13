# cih/roles.py
import re
from importlib.resources import files

from cih.contracts import AgentContract

ROLE_NAMES = ["high-planner", "planner", "plan-reviewer", "executor", "execution-reviewer"]

# Agent prompts ship as package data so the pip-installed CLI works with no
# repo-level .claude/ directory present (the repo's .claude/agents/*.md are
# symlinks back to these files).
_AGENTS_DIR = files("cih") / "_assets" / "agents"

_OUTPUT_SCHEMAS = {
    "high-planner": {
        "type": "object",
        "required": ["opportunities", "charters"],
        "properties": {
            "opportunities": {"type": "array"},
            "charters": {"type": "array"},
        },
    },
    "planner": {
        "type": "object",
        "required": ["tasks"],
        "properties": {"tasks": {"type": "array"}},
    },
    "plan-reviewer": {
        "type": "object",
        "required": ["approved", "feedback"],
        "properties": {"approved": {"type": "boolean"}, "feedback": {"type": "string"}},
    },
    "executor": {
        "type": "object",
        "required": ["commits"],
        "properties": {
            "commits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "task",
                        "red_sha",
                        "green_sha",
                        "test_command",
                        "declared_test_paths",
                    ],
                    "properties": {
                        "task": {"type": "string"},
                        "red_sha": {"type": "string"},
                        "green_sha": {"type": "string"},
                        "test_command": {"type": "array", "items": {"type": "string"}},
                        "declared_test_paths": {"type": "array", "items": {"type": "string"}},
                    },
                },
            }
        },
    },
    "execution-reviewer": {
        "type": "object",
        "required": ["approved", "reasons"],
        "properties": {"approved": {"type": "boolean"}, "reasons": {"type": "array"}},
    },
}


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL).strip()


def load_contracts(agents_dir=_AGENTS_DIR) -> dict[str, AgentContract]:
    contracts = {}
    for name in ROLE_NAMES:
        body = _strip_frontmatter((agents_dir / f"{name}.md").read_text())
        contracts[name] = AgentContract(
            role=name,
            agent_version="1.0.0",
            role_prompt=body,
            input_schema={"type": "object"},
            output_schema=_OUTPUT_SCHEMAS[name],
            allowed_tools=[],
        )
    return contracts
