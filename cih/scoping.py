import questionary
from typing import Protocol, Sequence, Any

from cih.config import RunConfig, ConfigError  # noqa: F401


class Asker(Protocol):
    """Injected I/O seam for the scoping interview. choices are (label, value) pairs."""

    def select(self, message: str, choices: Sequence[tuple[str, Any]], default: Any = None) -> Any: ...
    def checkbox(self, message: str, choices: Sequence[tuple[str, Any]]) -> list[Any]: ...
    def text(self, message: str, default: str = "") -> str: ...
    def confirm(self, message: str, default: bool = True) -> bool: ...
    def note(self, message: str) -> None: ...


def _to_choices(pairs: Sequence[tuple[str, Any]]) -> list[questionary.Choice]:
    return [questionary.Choice(title=label, value=value) for label, value in pairs]


class StubAsker:
    """Test double: returns queued answers in call order, records notes (mirrors StubRunner)."""

    def __init__(self, answers: Sequence[Any]):
        self._answers = list(answers)
        self._i = 0
        self.notes: list[str] = []

    def _next(self) -> Any:
        value = self._answers[self._i]
        self._i += 1
        return value

    def select(self, message, choices, default=None):
        return self._next()

    def checkbox(self, message, choices):
        return self._next()

    def text(self, message, default=""):
        return self._next()

    def confirm(self, message, default=True):
        return self._next()

    def note(self, message):
        self.notes.append(message)


def _ask_positive_int(asker: Asker, message: str, default: int) -> int:
    while True:
        raw = asker.text(message, default=str(default))
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            asker.note(f"Please enter a whole number (got {raw!r}).")
            continue
        if value <= 0:
            asker.note("Please enter a positive number.")
            continue
        return value
