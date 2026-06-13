import subprocess

from cih.tdd_verifier import TddVerdict, verify_tdd


def _repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
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
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True
    ).stdout.strip()


def test_clean_redgreen_passes(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    red = _commit(r, "red: failing test")
    (r / "src.py").write_text("def add(a, b):\n    return a + b\n")
    green = _commit(r, "green: implement add")
    v = verify_tdd(
        repo=r,
        red_sha=red,
        green_sha=green,
        test_command=["python", "-m", "pytest", "-q"],
        declared_test_paths=["test_src.py"],
    )
    assert isinstance(v, TddVerdict)
    assert v.eligible and v.passed
    assert v.red_failed and v.green_passed and v.full_suite_passed


def test_green_modifying_tests_is_blocked(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    red = _commit(r, "red")
    # 'green' cheats by weakening the test instead of fixing src
    (r / "test_src.py").write_text("from src import add\ndef test_add():\n    assert True\n")
    green = _commit(r, "green: cheat")
    v = verify_tdd(
        repo=r,
        red_sha=red,
        green_sha=green,
        test_command=["python", "-m", "pytest", "-q"],
        declared_test_paths=["test_src.py"],
    )
    assert not v.passed
    assert "green commit modified test paths" in v.reason


def test_red_that_does_not_fail_is_blocked(tmp_path):
    r = _repo(tmp_path)
    (r / "test_src.py").write_text("def test_trivial():\n    assert True\n")
    red = _commit(r, "red (but passes)")
    (r / "src.py").write_text("def add(a, b):\n    return a + b\n")
    green = _commit(r, "green")
    v = verify_tdd(
        repo=r,
        red_sha=red,
        green_sha=green,
        test_command=["python", "-m", "pytest", "-q"],
        declared_test_paths=["test_src.py"],
    )
    assert not v.passed
    assert "red commit did not fail" in v.reason


def _head(r):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True
    ).stdout.strip()


def test_red_collection_error_is_blocked(tmp_path):
    # C1: a red commit whose test fails to IMPORT (collection error, exit 2)
    # must NOT count as a valid red.
    r = _repo(tmp_path)
    (r / "test_src.py").write_text("import does_not_exist\ndef test_x():\n    assert True\n")
    red = _commit(r, "red (collection error)")
    (r / "src.py").write_text("def add(a, b):\n    return a + b\n")
    green = _commit(r, "green")
    v = verify_tdd(
        repo=r,
        red_sha=red,
        green_sha=green,
        test_command=["python", "-m", "pytest", "-q"],
        declared_test_paths=["test_src.py"],
    )
    assert not v.passed
    assert v.reason == "red commit failure was a collection/usage error, not a test failure"
    assert not v.red_failed


def test_dirty_working_tree_is_blocked(tmp_path):
    # I1: a dirty working tree before verification must block, HEAD unchanged.
    r = _repo(tmp_path)
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    red = _commit(r, "red: failing test")
    (r / "src.py").write_text("def add(a, b):\n    return a + b\n")
    green = _commit(r, "green: implement add")
    before = _head(r)
    # make an uncommitted modification to a tracked file
    (r / "src.py").write_text("def add(a, b):\n    return 999\n")
    v = verify_tdd(
        repo=r,
        red_sha=red,
        green_sha=green,
        test_command=["python", "-m", "pytest", "-q"],
        declared_test_paths=["test_src.py"],
    )
    assert not v.passed
    assert v.reason == "working tree dirty before verification"
    assert _head(r) == before


def test_unrelated_commits_blocked_by_ancestry(tmp_path):
    # I2: green that does not descend from red must be blocked.
    r = _repo(tmp_path)
    base = _head(r)
    (r / "test_src.py").write_text(
        "from src import add\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    red = _commit(r, "red: failing test")
    # build a second independent line off base
    subprocess.run(["git", "checkout", "-q", base], cwd=r, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "other"], cwd=r, check=True)
    (r / "other.py").write_text("x = 1\n")
    green = _commit(r, "green: unrelated line")
    subprocess.run(["git", "checkout", "-q", "master"], cwd=r, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=r, capture_output=True, text=True)
    v = verify_tdd(
        repo=r,
        red_sha=red,
        green_sha=green,
        test_command=["python", "-m", "pytest", "-q"],
        declared_test_paths=["test_src.py"],
    )
    assert not v.passed
    assert v.reason == "green is not a descendant of red"
