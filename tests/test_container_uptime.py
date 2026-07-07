"""Tests for skills/status/scripts/container-uptime.py — the script
the `status` skill calls to compute container uptime.

Adopted with the skill from jbaruch/nanoclaw-core (core#68 /
trusted#71); assertions unchanged, fixture loading adapted to this
repo's `load_script` conftest helper.

The module exposes `compute_uptime(now)` as a pure function: it takes
a fixed `now` so tests can pin time and assert deterministic output.
The CLI entrypoint (`main`) is just a JSON-printer wrapper.
"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import load_script

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REL = "skills/status/scripts/container-uptime.py"
SCRIPT_PATH = REPO_ROOT / SCRIPT_REL


@pytest.fixture
def container_uptime():
    """Fresh-loaded module under test per call so monkeypatched
    module-level constants don't leak across tests."""
    return load_script("container_uptime_under_test", SCRIPT_REL)


# Pinned test inputs — keeps the test deterministic per
# `jbaruch/coding-policy: testing-standards` ("Tests must be
# deterministic — no self-generated random test data").
FIXED_DOCKERENV_EPOCH = 1_700_000_000  # 2023-11-14T22:13:20Z
FIXED_NOW = datetime.datetime(
    2023, 11, 16, 22, 13, 20, tzinfo=datetime.timezone.utc
)  # exactly 2 days, 0 hours later


def test_missing_dockerenv_returns_unknown(container_uptime, monkeypatch):
    """When /.dockerenv is absent (dev host, non-container env),
    compute_uptime must return the unknown shape — `started: None`,
    `uptime_text: "unknown"`. Per the script's docstring this is an
    expected case, NOT an error: status skill renders it as 'unknown'
    instead of failing."""
    monkeypatch.setattr(container_uptime, "DOCKERENV_PATH", "/nonexistent/.dockerenv")
    result = container_uptime.compute_uptime(FIXED_NOW)
    assert result == {"uptime_text": "unknown", "started": None}


def test_present_dockerenv_returns_deterministic_uptime(container_uptime, monkeypatch, tmp_path):
    """With a /.dockerenv at a fixed mtime and `now` pinned to exactly
    2 days later, compute_uptime must produce '2d 0h (since <ISO>)'
    and the matching ISO timestamp. Tests both branches of the format
    string (days, hours-after-int-divide) by construction."""
    fake_dockerenv = tmp_path / ".dockerenv"
    fake_dockerenv.touch()
    os.utime(fake_dockerenv, (FIXED_DOCKERENV_EPOCH, FIXED_DOCKERENV_EPOCH))
    monkeypatch.setattr(container_uptime, "DOCKERENV_PATH", str(fake_dockerenv))

    result = container_uptime.compute_uptime(FIXED_NOW)

    assert result["started"] == "2023-11-14T22:13:20Z"
    assert result["uptime_text"] == "2d 0h (since 2023-11-14T22:13:20Z)"


def test_partial_day_uptime_formats_hours(container_uptime, monkeypatch, tmp_path):
    """Pin mtime to 5 hours before `now` (less than 1 day) — must
    render as '0d 5h ...' so the day/hour split is correct on
    sub-day uptimes too. Catches off-by-one or wrong-units bugs in
    the format string."""
    fake_dockerenv = tmp_path / ".dockerenv"
    fake_dockerenv.touch()
    five_hours_before_now = int(FIXED_NOW.timestamp()) - (5 * 3600)
    os.utime(fake_dockerenv, (five_hours_before_now, five_hours_before_now))
    monkeypatch.setattr(container_uptime, "DOCKERENV_PATH", str(fake_dockerenv))

    result = container_uptime.compute_uptime(FIXED_NOW)

    assert result["started"] == "2023-11-16T17:13:20Z"
    assert result["uptime_text"].startswith("0d 5h")


def test_future_mtime_clamps_to_zero_uptime(container_uptime, monkeypatch, tmp_path):
    """Clock skew or filesystem anomalies can put /.dockerenv's mtime
    ahead of `now`. The age must clamp to zero — '0d 0h', never a
    negative '-1d 23h' — while `started` still reports the raw mtime."""
    fake_dockerenv = tmp_path / ".dockerenv"
    fake_dockerenv.touch()
    one_hour_after_now = int(FIXED_NOW.timestamp()) + 3600
    os.utime(fake_dockerenv, (one_hour_after_now, one_hour_after_now))
    monkeypatch.setattr(container_uptime, "DOCKERENV_PATH", str(fake_dockerenv))

    result = container_uptime.compute_uptime(FIXED_NOW)

    assert result["uptime_text"].startswith("0d 0h"), (
        f"Future mtime must clamp to zero uptime, got {result['uptime_text']!r}"
    )
    assert result["started"] == "2023-11-16T23:13:20Z"


def test_main_emits_single_line_json():
    """The CLI entrypoint must produce a single-line JSON payload on
    stdout that downstream callers can parse (the SKILL.md example
    pipes through `python3 -c 'json.load(sys.stdin)'`). Run as a
    subprocess; on a host without /.dockerenv the script falls
    through to the missing branch, and either way the JSON contract
    is what's verified."""
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    # Single line plus trailing newline — the script writes
    # `json.dump(...)` then `'\n'` explicitly.
    assert completed.stdout.endswith("\n")
    payload = json.loads(completed.stdout)
    # On the test host /.dockerenv almost certainly doesn't exist, so
    # we expect the unknown shape. (If it does exist, we still have a
    # well-formed JSON payload, which is the contract we're verifying.)
    assert "uptime_text" in payload
    assert "started" in payload
    if payload["started"] is None:
        assert payload["uptime_text"] == "unknown"
