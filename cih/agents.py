# cih/agents.py
import json
import subprocess
from typing import Protocol
from cih.contracts import AgentContract

class AgentRunner(Protocol):
    def run(self, contract: AgentContract, input_data: dict) -> dict: ...

class StubRunner:
    """Test double: returns canned responses keyed by role."""
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[dict] = []

    def run(self, contract: AgentContract, input_data: dict) -> dict:
        self.calls.append({"role": contract.role, "input": input_data})
        if contract.role not in self.responses:
            raise KeyError(f"no stub response for role {contract.role}")
        return self.responses[contract.role]

class ClaudeCliRunner:
    """Headless adapter: drives `claude -p --append-system-prompt`.

    Flags precede the prompt; output is expected as JSON on stdout.
    """
    def __init__(self, cwd: str, extra_args: list[str] | None = None):
        self.cwd = cwd
        self.extra_args = extra_args or []

    def run(self, contract: AgentContract, input_data: dict) -> dict:
        prompt = json.dumps(input_data)
        cmd = ["claude", "-p", "--output-format", "json",
               "--append-system-prompt", contract.role_prompt,
               *self.extra_args, "--", prompt]
        proc = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"claude failed for {contract.role}: {proc.stderr}")
        envelope = json.loads(proc.stdout)
        # claude -p --output-format json wraps content in {"result": "..."}
        result = envelope.get("result", envelope)
        return result if isinstance(result, dict) else json.loads(result)

def invoke(runner: AgentRunner, contract: AgentContract, input_data: dict) -> dict:
    output = runner.run(contract, input_data)
    contract.validate_output(output)
    return output
