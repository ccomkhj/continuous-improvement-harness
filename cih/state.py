import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

SCHEMA_VERSION = 1

@dataclass
class StateHeader:
    run_id: str
    iteration_id: Optional[str]
    team_id: Optional[str]
    attempt_id: Optional[str]
    status: str
    owner: str

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def write_state(path: Path, header: StateHeader, body: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    created_at = _now()
    if path.exists():
        try:
            created_at = json.loads(path.read_text())["created_at"]
        except (json.JSONDecodeError, KeyError):
            pass
    doc = {"schema_version": SCHEMA_VERSION, **asdict(header),
           "created_at": created_at, "updated_at": _now(), "body": body}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)  # atomic on same filesystem
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def read_state(path: Path) -> dict:
    return json.loads(Path(path).read_text())
