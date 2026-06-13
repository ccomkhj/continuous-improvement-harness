# cih/ledger.py
import hashlib
import re
from dataclasses import asdict, dataclass

from cih.transitions import Status, assert_transition


def fingerprint(title: str, scope: str) -> str:
    norm = re.sub(r"\s+", " ", title.strip().lower())
    return hashlib.sha256(f"{norm}|{scope}".encode()).hexdigest()[:16]

@dataclass
class Opportunity:
    fp: str
    title: str
    scope: str
    value: float
    confidence: float
    effort: float
    risk: float
    rationale: str
    state: str = "open"
    attempt_count: int = 0
    cooldown_until: int | None = None

class Ledger:
    def __init__(self):
        self._items: dict[str, Opportunity] = {}

    def upsert(self, opp: Opportunity) -> None:
        existing = self._items.get(opp.fp)
        if existing and existing.state in ("merged", "expired"):
            return  # terminal; ignore re-discovery
        if existing:
            opp.attempt_count = existing.attempt_count
            opp.state = existing.state
            opp.cooldown_until = existing.cooldown_until
        self._items[opp.fp] = opp

    def get(self, fp: str) -> Opportunity | None:
        return self._items.get(fp)

    def _set_state(self, o, dst: str) -> None:
        # A same-state write is an idempotent no-op (e.g. a still-cooling item
        # re-entering cooldown on a subsequent failed retry); it is trivially
        # monotonic, so it does not need a table edge.
        if o.state == dst:
            return
        assert_transition(Status(o.state), Status(dst))
        o.state = dst

    def _refresh_cooldowns(self, current_iteration: int | None) -> None:
        if current_iteration is None:
            return
        for o in self._items.values():
            if o.state == "cooldown" and o.cooldown_until is not None \
                    and current_iteration >= o.cooldown_until:
                self._set_state(o, "open")
                o.cooldown_until = None

    def select_open(self, value_threshold: float,
                    current_iteration: int | None = None) -> list[Opportunity]:
        self._refresh_cooldowns(current_iteration)
        return [o for o in self._items.values()
                if o.state == "open" and o.value >= value_threshold]

    def is_dry(self, value_threshold: float, current_iteration: int) -> bool:
        # Spec §5: dry = no open opportunity above threshold AND no retryable
        # opportunity OUTSIDE cooldown. select_open() refreshes cooldowns first,
        # so items whose cooldown has elapsed are already reopened and counted;
        # items still cooling are correctly excluded.
        return not self.select_open(value_threshold, current_iteration)

    def mark_merged(self, fp: str) -> None:
        self._set_state(self._items[fp], "merged")

    def mark_cooldown(self, fp: str, current_iteration: int,
                      cooldown_iterations: int) -> None:
        o = self._items[fp]
        self._set_state(o, "cooldown")
        o.cooldown_until = current_iteration + cooldown_iterations

    def record_attempt_failure(self, fp: str, current_iteration: int,
                               cooldown_iterations: int, max_attempts: int) -> None:
        o = self._items[fp]
        o.attempt_count += 1
        if o.attempt_count >= max_attempts:
            self._set_state(o, "expired")
            o.cooldown_until = None
        else:
            self.mark_cooldown(fp, current_iteration, cooldown_iterations)

    def to_dict(self) -> dict:
        return {fp: asdict(o) for fp, o in self._items.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "Ledger":
        led = cls()
        for fp, raw in d.items():
            led._items[fp] = Opportunity(**raw)
        return led
