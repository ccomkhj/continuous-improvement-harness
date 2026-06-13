# cih/contracts.py
import hashlib
import json
from dataclasses import dataclass, field

from jsonschema import ValidationError, validate


class OutputValidationError(Exception):
    pass


@dataclass
class AgentContract:
    role: str
    agent_version: str
    role_prompt: str
    input_schema: dict
    output_schema: dict
    allowed_tools: list = field(default_factory=list)
    runtime_adapter_settings: dict = field(default_factory=dict)

    def validate_output(self, output: dict) -> None:
        try:
            validate(instance=output, schema=self.output_schema)
        except ValidationError as e:
            raise OutputValidationError(f"{self.role} output invalid: {e.message}") from e

    def prompt_hash(self) -> str:
        blob = json.dumps(
            {
                "prompt": self.role_prompt,
                "in": self.input_schema,
                "out": self.output_schema,
                "v": self.agent_version,
                "tools": self.allowed_tools,
                "adapter": self.runtime_adapter_settings,
            },
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
