import subprocess
from pathlib import Path
from cih.tdd_verifier import verify_tdd, TddVerdict

def _repo(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "src.py").write_text("def add(a, b):\n    raise NotImplementedError\n")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline (no tests)"], cwd=r, check=True)
    return r

def _commit(r, msg):
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=r, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=r,
                          capture_output=True, text=True).stdout.strip()

def test_clean_redgreen_passes(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert add(1, 2) == 3\n")
    red = _commit(r, "red: failing test")
    (r / "src.py").write_text("def add(a, b):\n    return a + b\n")
    green = _commit(r, "green: implement add")
    v = verify_tdd(repo=r, red_sha=red, green_sha=green,
                   test_command=["python", "-m", "pytest", "-q"],
                   declared_test_paths=["test_src.py"])
    assert isinstance(v, TddVerdict)
    assert v.eligible and v.passed
    assert v.red_failed and v.green_passed and v.full_suite_passed

def test_green_modifying_tests_is_blocked(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert add(1, 2) == 3\n")
    red = _commit(r, "red")
    # 'green' cheats by weakening the test instead of fixing src
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert True\n")
    green = _commit(r, "green: cheat")
    v = verify_tdd(repo=r, red_sha=red, green_sha=green,
                   test_command=["python", "-m", "pytest", "-q"],
                   declared_test_paths=["test_src.py"])
    assert not v.passed
    assert "green commit modified test paths" in v.reason

def test_red_that_does_not_fail_is_blocked(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text("def test_trivial():\n    assert True\n")
    red = _commit(r, "red (but passes)")
    (r / "src.py").write_text("def add(a, b):\n    return a + b\n")
    green = _commit(r, "green")
    v = verify_tdd(repo=r, red_sha=red, green_sha=green,
                   test_command=["python", "-m", "pytest", "-q"],
                   declared_test_paths=["test_src.py"])
    assert not v.passed
    assert "red commit did not fail" in v.reason
