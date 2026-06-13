from collections.abc import Sequence
from typing import Any, Protocol

import questionary

from cih.config import ConfigError, RunConfig  # noqa: F401


class Asker(Protocol):
    """Injected I/O seam for the scoping interview. choices are (label, value) pairs."""

    def select(
        self, message: str, choices: Sequence[tuple[str, Any]], default: Any = None
    ) -> Any: ...
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


MODE_CHOICES = [
    ("Fixed number of iterations", "fixed-N"),
    ("Run until converged", "until-converged"),
]
FOCUS_PRESETS = ["tests", "performance", "security", "documentation", "types", "refactor"]
VALUE_CHOICES = [
    ("Conservative (0.7) — only high-value opportunities", 0.7),
    ("Balanced (0.5) — default", 0.5),
    ("Aggressive (0.3) — more, smaller wins", 0.3),
]


def _summary(
    target_repo, state_dir, mode, iterations, max_iterations, focus_areas, value_threshold
) -> str:
    bound = f"iterations={iterations}" if mode == "fixed-N" else f"max_iterations={max_iterations}"
    focus = ", ".join(focus_areas) if focus_areas else "(broad audit)"
    return (
        "Planned run:\n"
        f"  target_repo:     {target_repo}\n"
        f"  state_dir:       {state_dir}\n"
        f"  mode:            {mode} ({bound})\n"
        f"  focus_areas:     {focus}\n"
        f"  value_threshold: {value_threshold}"
    )


def run_scoping_interview(target_repo: str, state_dir: str, asker: Asker) -> RunConfig:
    # Fail fast on bad paths BEFORE asking anything — the interview cannot fix them.
    RunConfig._validate_paths(target_repo, state_dir)

    while True:
        mode = asker.select("Run mode?", MODE_CHOICES, default="until-converged")
        iterations = None
        max_iterations = 25
        if mode == "fixed-N":
            iterations = _ask_positive_int(asker, "How many iterations?", 3)
        else:
            max_iterations = _ask_positive_int(asker, "Max iterations (safety cap)?", 25)

        selected = asker.checkbox(
            "Focus areas (space to toggle, enter to accept — optional)?",
            [(f, f) for f in FOCUS_PRESETS],
        )
        extra = asker.text("Other focus areas (comma-separated, optional)?", default="")
        focus_areas = list(selected) + [s.strip() for s in extra.split(",") if s.strip()]

        value_threshold = asker.select("How aggressive should it be?", VALUE_CHOICES, default=0.5)

        asker.note(
            _summary(
                target_repo,
                state_dir,
                mode,
                iterations,
                max_iterations,
                focus_areas,
                value_threshold,
            )
        )
        if not asker.confirm("Go ahead with this run?", default=True):
            asker.note("Okay — let's redo the scoping.")
            continue

        return RunConfig.create(
            mode=mode,
            iterations=iterations,
            max_iterations=max_iterations,
            target_repo=target_repo,
            state_dir=state_dir,
            focus_areas=focus_areas,
            value_threshold=value_threshold,
        )


class QuestionaryAsker:
    """Real Asker over questionary. Cancel (Ctrl-C / ESC -> None) raises KeyboardInterrupt."""

    @staticmethod
    def _resolve(question):
        answer = question.ask()
        if answer is None:
            raise KeyboardInterrupt("scoping interview cancelled")
        return answer

    def select(self, message, choices, default=None):
        return self._resolve(
            questionary.select(message, choices=_to_choices(choices), default=default)
        )

    def checkbox(self, message, choices):
        return self._resolve(questionary.checkbox(message, choices=_to_choices(choices)))

    def text(self, message, default=""):
        return self._resolve(questionary.text(message, default=default))

    def confirm(self, message, default=True):
        return self._resolve(questionary.confirm(message, default=default))

    def note(self, message):
        questionary.print(message)
