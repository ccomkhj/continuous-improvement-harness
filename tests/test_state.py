from cih.state import SCHEMA_VERSION, StateHeader, read_state, write_state


def _header():
    return StateHeader(
        run_id="run-1", iteration_id="iter-001", team_id=None,
        attempt_id=None, status="open", owner="orchestrator",
    )

def test_write_then_read_roundtrips_with_header(tmp_path):
    path = tmp_path / "run.json"
    write_state(path, _header(), {"mode": "fixed-N"})
    doc = read_state(path)
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["run_id"] == "run-1"
    assert doc["status"] == "open"
    assert doc["owner"] == "orchestrator"
    assert doc["body"] == {"mode": "fixed-N"}
    assert "created_at" in doc and "updated_at" in doc

def test_write_is_atomic_no_temp_left_behind(tmp_path):
    path = tmp_path / "run.json"
    write_state(path, _header(), {"x": 1})
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "run.json"]
    assert leftovers == []

def test_rewrite_preserves_created_at_bumps_updated_at(tmp_path):
    path = tmp_path / "run.json"
    write_state(path, _header(), {"v": 1})
    first = read_state(path)
    write_state(path, _header(), {"v": 2})
    second = read_state(path)
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]
    assert second["body"] == {"v": 2}
