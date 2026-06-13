# cih/agents.py
import json
import re
import subprocess
from typing import Protocol

from cih.contracts import AgentContract

# Matches a fenced block: ```json ... ``` or ``` ... ``` (language tag optional).
# DOTALL so the body spans newlines; non-greedy so each fence is captured separately.
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json(text):
    """Extract a JSON object from model text that may be bare JSON, wrapped in a
    markdown code fence, and/or surrounded by prose.

    Strategy, most-specific first:
      1. A ```json ... ``` / ``` ... ``` fence — prefer it so a stray '{' in the
         prose is never grabbed; use the LAST fence that parses (a preamble may
         show an illustrative non-final fence before the real answer).
      2. Else slice from the first '{' to the last '}'.
      3. Else parse the whole string.
    Raises json.JSONDecodeError (or TypeError if text is not a str), so the
    caller's existing OutputValidationError handling is preserved unchanged.
    """
    if not isinstance(text, str):
        raise TypeError(f"expected str, got {type(text).__name__}")
    last_err = None
    parsed = _MISSING = object()
    for m in _FENCE_RE.finditer(text):
        try:
            parsed = json.loads(m.group(1).strip())  # keep last fence that parses
        except json.JSONDecodeError as e:
            last_err = e
    if parsed is not _MISSING:
        return parsed
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            last_err = e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise (last_err or e) from e


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
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(contract.output_schema),
            "--append-system-prompt",
            contract.role_prompt,
            *self.extra_args,
            "--",
            prompt,
        ]
        proc = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"claude failed for {contract.role}: {proc.stderr}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"{contract.role}: non-JSON stdout from claude -p: {proc.stdout[:500]!r}"
            ) from e
        if envelope.get("is_error"):
            raise RuntimeError(f"{contract.role}: claude reported error: {envelope.get('result')}")
        # With --json-schema, claude returns the schema-conforming object in
        # `structured_output` and leaves `result` as a prose summary. Prefer it.
        structured = envelope.get("structured_output")
        if isinstance(structured, dict):
            return structured
        if isinstance(structured, str) and structured.strip():
            try:
                return _extract_json(structured)
            except (TypeError, json.JSONDecodeError):
                pass  # fall through to `result`
        result = envelope.get("result")
        if isinstance(result, dict):
            return result
        try:
            return _extract_json(result)
        except (TypeError, json.JSONDecodeError) as e:
            from cih.contracts import OutputValidationError

            raise OutputValidationError(f"{contract.role}: result was not JSON: {result!r}") from e


def invoke(runner: AgentRunner, contract: AgentContract, input_data: dict) -> dict:
    output = runner.run(contract, input_data)
    contract.validate_output(output)
    return output
