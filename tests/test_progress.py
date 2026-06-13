import re

from cih.progress import append_progress, notify


def test_append_progress_creates_file(tmp_path):
    sd = tmp_path / "state"
    append_progress(sd, "first line")
    p = sd / "progress.md"
    assert p.exists()
    assert "first line" in p.read_text()


def test_append_progress_is_append_only(tmp_path):
    sd = tmp_path / "state"
    append_progress(sd, "first line")
    append_progress(sd, "second line")
    lines = (sd / "progress.md").read_text().splitlines()
    assert len(lines) == 2
    assert "first line" in lines[0]
    assert "second line" in lines[1]


def test_append_progress_line_starts_with_iso_timestamp(tmp_path):
    sd = tmp_path / "state"
    append_progress(sd, "hello")
    line = (sd / "progress.md").read_text().splitlines()[0]
    # ISO-8601 UTC timestamp prefix, e.g. 2026-06-06T12:34:56.789+00:00
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
    assert line.endswith("hello")


def test_notify_always_appends_to_progress(tmp_path, monkeypatch):
    monkeypatch.delenv("CIH_NOTIFY_CMD", raising=False)
    sd = tmp_path / "state"
    notify(sd, "milestone X")
    assert "milestone X" in (sd / "progress.md").read_text()


def test_notify_invokes_cmd_with_line_as_final_arg(tmp_path, monkeypatch):
    sd = tmp_path / "state"
    sink = tmp_path / "sink.txt"
    # A tiny notifier that records its final argument (the message).
    script = tmp_path / "notify.sh"
    script.write_text(f'#!/bin/sh\nprintf "$1" "$1" > "{sink}"\n')
    script.chmod(0o755)
    monkeypatch.setenv("CIH_NOTIFY_CMD", str(script))
    notify(sd, "team t1 PASSED")
    assert sink.read_text() == "team t1 PASSED"
    assert "team t1 PASSED" in (sd / "progress.md").read_text()


def test_notify_without_cmd_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.delenv("CIH_NOTIFY_CMD", raising=False)
    sd = tmp_path / "state"
    notify(sd, "no sink configured")  # must not raise


def test_notify_swallows_failing_cmd(tmp_path, monkeypatch):
    sd = tmp_path / "state"
    monkeypatch.setenv("CIH_NOTIFY_CMD", "/nonexistent/notifier-binary")
    notify(sd, "still logged")  # must not raise even if the command is missing
    assert "still logged" in (sd / "progress.md").read_text()
