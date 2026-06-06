import re
from pathlib import Path
from cih.progress import append_progress


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
