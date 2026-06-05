# cih/ledger.py
import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

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
    cooldown_until: Optional[int] = None

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

    def get(self, fp: str) -> Optional[Opportunity]:
        return self._items.get(fp)

    def _refresh_cooldowns(self, current_iteration: Optional[int]) -> None:
        if current_iteration is None:
            return
        for o in self._items.values():
            if o.state == "cooldown" and o.cooldown_until is not None \
                    and current_iteration >= o.cooldown_until:
                o.state = "open"
                o.cooldown_until = None

    def select_open(self, value_threshold: float,
                    current_iteration: Optional[int] = None) -> list[Opportunity]:
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
        self._items[fp].state = "merged"

    def mark_cooldown(self, fp: str, current_iteration: int,
                      cooldown_iterations: int) -> None:
        o = self._items[fp]
        o.state = "cooldown"
        o.cooldown_until = current_iteration + cooldown_iterations

    def record_attempt_failure(self, fp: str, current_iteration: int,
                               cooldown_iterations: int, max_attempts: int) -> None:
        o = self._items[fp]
        o.attempt_count += 1
        if o.attempt_count >= max_attempts:
            o.state = "expired"
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
