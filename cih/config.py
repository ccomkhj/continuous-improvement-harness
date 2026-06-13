import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


_MODES = {"fixed-N", "until-converged"}

DEPTH_BUDGET = {"low": 3, "medium": 6, "high": 10}
DEFAULT_DEPTH = "medium"


def depth_budget(name: str | None = None) -> int:
    """Map a --depth name to its question budget (upper bound). None → default."""
    if name is None:
        name = DEFAULT_DEPTH
    if name not in DEPTH_BUDGET:
        raise ConfigError(
            f"depth must be one of {sorted(DEPTH_BUDGET, key=DEPTH_BUDGET.__getitem__)} (got {name!r})"
        )
    return DEPTH_BUDGET[name]


@dataclass
class RunConfig:
    mode: str
    target_repo: str
    state_dir: str
    iterations: int | None = None
    max_iterations: int = 25
    budget_cap: int | None = None
    focus_areas: list[str] = field(default_factory=list)
    brief: str = ""
    value_threshold: float = 0.5
    convergence_dry_streak: int = 2
    plan_review_retries: int = 2
    exec_review_retries: int = 2
    max_teams_per_iteration: int = 4
    integration_retries: int = 2
    per_team_attempt_cap: int = 4
    cooldown_iterations: int = 2
    opportunity_max_attempts: int = 3
    tdd_adapter: str = "pytest"

    @staticmethod
    def _validate_paths(target_repo: str, state_dir: str) -> None:
        for label, p in (("target_repo", target_repo), ("state_dir", state_dir)):
            if not os.path.isabs(p):
                raise ConfigError(f"{label} must be an absolute path: {p}")
        t = Path(target_repo).resolve()
        s = Path(state_dir).resolve()
        if t == s:
            raise ConfigError("target_repo and state_dir must be distinct")
        if t in s.parents or s in t.parents:
            raise ConfigError("state_dir must not be nested inside target_repo (or vice versa)")
        for label, p in (("target_repo", t), ("state_dir", s)):
            if not p.is_dir():
                raise ConfigError(f"{label} must be an existing directory: {p}")

    @classmethod
    def create(cls, **kwargs) -> "RunConfig":
        mode = kwargs.get("mode")
        if mode not in _MODES:
            raise ConfigError(f"mode must be one of {_MODES}")
        iterations = kwargs.get("iterations")
        if mode == "fixed-N":
            if not isinstance(iterations, int) or iterations <= 0:
                raise ConfigError("fixed-N mode requires iterations to be a positive int")
        elif mode == "until-converged":
            if iterations is not None:
                raise ConfigError("until-converged mode must not set iterations")
        cls._validate_paths(kwargs["target_repo"], kwargs["state_dir"])
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunConfig":
        return cls.create(**d)
