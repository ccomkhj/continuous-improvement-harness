import pytest

from cih.config import DEFAULT_DEPTH, DEPTH_BUDGET, ConfigError, RunConfig, depth_budget


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

def test_rejects_nonexistent_paths(tmp_path):
    state = tmp_path / "state"; state.mkdir()
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ConfigError):
        RunConfig.create(mode="fixed-N", iterations=1,
                         target_repo=str(missing), state_dir=str(state))

def test_fixed_n_requires_positive_iterations(tmp_path):
    target = tmp_path / "t"; state = tmp_path / "s"; target.mkdir(); state.mkdir()
    with pytest.raises(ConfigError):
        RunConfig.create(mode="fixed-N", iterations=None,
                         target_repo=str(target), state_dir=str(state))
    with pytest.raises(ConfigError):
        RunConfig.create(mode="fixed-N", iterations=0,
                         target_repo=str(target), state_dir=str(state))

def test_until_converged_forbids_iterations(tmp_path):
    target = tmp_path / "t"; state = tmp_path / "s"; target.mkdir(); state.mkdir()
    with pytest.raises(ConfigError):
        RunConfig.create(mode="until-converged", iterations=2,
                         target_repo=str(target), state_dir=str(state))

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

def test_depth_budget_values():
    assert depth_budget("low") == 3
    assert depth_budget("medium") == 6
    assert depth_budget("high") == 10

def test_depth_budget_default():
    assert DEFAULT_DEPTH == "medium"
    assert depth_budget(None) == 6
    assert depth_budget(DEFAULT_DEPTH) == 6

def test_depth_budget_rejects_unknown():
    with pytest.raises(ConfigError, match=r"low.*medium.*high"):
        depth_budget("deep")

def test_depth_budget_map_exact():
    assert DEPTH_BUDGET == {"low": 3, "medium": 6, "high": 10}
