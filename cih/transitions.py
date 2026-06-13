from enum import Enum


class Status(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    MERGED = "merged"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    COOLDOWN = "cooldown"
    EXPIRED = "expired"


class InvalidTransition(Exception):
    pass


# monotonic-ish: terminal states cannot leave; cooldown can re-open
_ALLOWED = {
    Status.OPEN: {
        Status.IN_PROGRESS,
        Status.MERGED,
        Status.COOLDOWN,
        Status.DEFERRED,
        Status.REJECTED,
        Status.EXPIRED,
    },
    Status.IN_PROGRESS: {Status.MERGED, Status.REJECTED, Status.COOLDOWN},
    Status.COOLDOWN: {Status.OPEN, Status.EXPIRED},
    Status.DEFERRED: {Status.OPEN, Status.EXPIRED},
    Status.REJECTED: {Status.COOLDOWN, Status.EXPIRED, Status.OPEN},
    Status.MERGED: set(),
    Status.EXPIRED: set(),
}


def is_valid_transition(src: Status, dst: Status) -> bool:
    return dst in _ALLOWED.get(src, set())


def assert_transition(src: Status, dst: Status) -> None:
    if not is_valid_transition(src, dst):
        raise InvalidTransition(f"{src.value} -> {dst.value} is not allowed")
