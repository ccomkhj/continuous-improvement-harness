# tests/test_staging.py
import subprocess
from pathlib import Path

import pytest

from cih.staging import StagingError, stage_files


def _init_repo(path: Path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)


def test_stages_only_declared_files(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    stage_files(tmp_path, ["a.py"])
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.split()
    assert staged == ["a.py"]


def test_rejects_add_all_tokens(tmp_path):
    _init_repo(tmp_path)
    for token in ("-A", ".", "*", ":/", "--all"):
        with pytest.raises(StagingError):
            stage_files(tmp_path, [token])


def test_rejects_pathspec_magic_and_globs_and_dirs(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "secret.key").write_text("topsecret")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("c")
    bypasses = [":(glob)**", ":(top)", "*.py", "sub", "./", "/abs/path", "../traversal"]
    for token in bypasses:
        with pytest.raises(StagingError):
            stage_files(tmp_path, [token])
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=tmp_path, capture_output=True, text=True
        ).stdout.split()
        # secret must never be staged by any bypass attempt
        assert "secret.key" not in staged, f"token {token!r} staged secret.key"
        assert staged == [], f"token {token!r} staged {staged}"


def test_rejects_forbidden_path(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / ".cih").mkdir()
    (tmp_path / ".cih" / "run.json").write_text("{}")
    with pytest.raises(StagingError):
        stage_files(tmp_path, [".cih/run.json"])
