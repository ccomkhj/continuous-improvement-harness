# tests/test_staging.py
import subprocess
import pytest
from pathlib import Path
from cih.staging import stage_files, StagingError

def _init_repo(path: Path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)

def test_stages_only_declared_files(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    stage_files(tmp_path, ["a.py"])
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                            cwd=tmp_path, capture_output=True, text=True).stdout.split()
    assert staged == ["a.py"]

def test_rejects_add_all_tokens(tmp_path):
    _init_repo(tmp_path)
    for token in ("-A", ".", "*", ":/", "--all"):
        with pytest.raises(StagingError):
            stage_files(tmp_path, [token])

def test_rejects_forbidden_path(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / ".cih").mkdir()
    (tmp_path / ".cih" / "run.json").write_text("{}")
    with pytest.raises(StagingError):
        stage_files(tmp_path, [".cih/run.json"])
