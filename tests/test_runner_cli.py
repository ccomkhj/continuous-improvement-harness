from pathlib import Path
from cih.runner import parse_args, build_config

def test_parse_args_fixed_n(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "fixed-N", "--iterations", "3",
                     "--target-repo", str(t), "--state-dir", str(s),
                     "--focus", "tests", "--focus", "perf"])
    cfg = build_config(ns)
    assert cfg.mode == "fixed-N"
    assert cfg.iterations == 3
    assert cfg.focus_areas == ["tests", "perf"]

def test_parse_args_until_converged(tmp_path):
    t = tmp_path / "t"; s = tmp_path / "s"; t.mkdir(); s.mkdir()
    ns = parse_args(["--mode", "until-converged",
                     "--target-repo", str(t), "--state-dir", str(s)])
    cfg = build_config(ns)
    assert cfg.mode == "until-converged"
    assert cfg.iterations is None
