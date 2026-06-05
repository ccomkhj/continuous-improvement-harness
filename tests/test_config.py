import pytest
from cih.config import RunConfig, ConfigError

def test_valid_config(tmp_path):
    target = tmp_path / "target"; state = tmp_path / "state"
    target.mkdir(); state.mkdir()
    cfg = RunConfig.create(mode="fixed-N", iterations=3,
                           target_repo=str(target), state_dir=str(state))
    assert cfg.mode == "fixed-N"
    assert cfg.iterations == 3
    assert cfg.plan_review_retries == 2  # default
    assert cfg.tdd_adapter == "pytest"

def test_rejects_relative_paths(tmp_path):
    with pytest.raises(ConfigError):
        RunConfig.create(mode="fixed-N", iterations=1,
                         target_repo="relative/target", state_dir=str(tmp_path))

def test_rejects_state_dir_nested_in_target(tmp_path):
    target = tmp_path / "target"; target.mkdir()
    nested = target / "state"; nested.mkdir()
    with pytest.raises(ConfigError):
        RunConfig.create(mode="fixed-N", iterations=1,
                         target_repo=str(target), state_dir=str(nested))

def test_rejects_unknown_mode(tmp_path):
    target = tmp_path / "t"; state = tmp_path / "s"; target.mkdir(); state.mkdir()
    with pytest.raises(ConfigError):
        RunConfig.create(mode="bogus", iterations=1,
                         target_repo=str(target), state_dir=str(state))

def test_roundtrip_to_dict(tmp_path):
    target = tmp_path / "t"; state = tmp_path / "s"; target.mkdir(); state.mkdir()
    cfg = RunConfig.create(mode="until-converged", target_repo=str(target),
                           state_dir=str(state), focus_areas=["tests"])
    d = cfg.to_dict()
    assert d["focus_areas"] == ["tests"]
    assert RunConfig.from_dict(d).focus_areas == ["tests"]
