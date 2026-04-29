"""Tests for skills/trusted-memory/scripts/append-to-daily-log.py.

Contract:
  - Creates daily file with `# Daily Summary — YYYY-MM-DD` header on
    first append.
  - Appends one or many lines under `LOCK_EX` on `<daily-file>.lock`.
  - Atomic write (tempfile + fsync + os.replace), preserves mode.
  - Reports `monotonic: false` when a new entry's `HH:MM UTC` prefix
    is earlier than the existing tail; still appends.
  - Concurrent writers serialise — append from process B does not
    overwrite append from process A.
  - Exits 0 on success with single-line JSON to stdout; exits 2 on
    hard error with diagnostic on stderr.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/trusted-memory/scripts/append-to-daily-log.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / SCRIPT_REL


def _run_cli(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the helper as a subprocess. Used for end-to-end tests
    where the process boundary matters (lock contention, exit codes,
    stdout/stderr separation)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


@pytest.fixture
def group_dir(tmp_path):
    d = tmp_path / "group_daily"
    d.mkdir()
    return d


@pytest.fixture
def trusted_dir(tmp_path):
    d = tmp_path / "trusted_daily"
    d.mkdir()
    return d


def test_creates_file_with_header_on_first_append(group_dir):
    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "2026-04-29",
            "--line",
            "- 09:13 UTC — first heartbeat",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["appended_lines"] == 1
    assert payload["monotonic"] is True

    daily = group_dir / "2026-04-29.md"
    assert daily.exists()
    content = daily.read_text()
    assert content.startswith("# Daily Summary — 2026-04-29\n")
    assert "- 09:13 UTC — first heartbeat\n" in content


def test_appends_to_existing_file_preserving_prior_lines(group_dir):
    daily = group_dir / "2026-04-29.md"
    daily.write_text(
        "# Daily Summary — 2026-04-29\n"
        "- 02:54 UTC — early heartbeat one\n"
        "- 07:55 UTC — early heartbeat two\n"
    )

    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "2026-04-29",
            "--line",
            "- 09:13 UTC — later heartbeat",
        ]
    )
    assert proc.returncode == 0, proc.stderr

    content = daily.read_text()
    # All three entries must be present — the breaking incident in
    # jbaruch/nanoclaw#266 was an LLM-driven Write that dropped the
    # earlier heartbeats. The helper must never lose them.
    assert "- 02:54 UTC — early heartbeat one\n" in content
    assert "- 07:55 UTC — early heartbeat two\n" in content
    assert "- 09:13 UTC — later heartbeat\n" in content


def test_lines_file_appends_each_non_blank_line(group_dir, tmp_path):
    lines_file = tmp_path / "lines.txt"
    lines_file.write_text(
        "- 10:00 UTC — first batch entry\n"
        "\n"  # blank line — must be skipped
        "- 10:05 UTC — second batch entry\n"
    )

    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "2026-04-29",
            "--lines-file",
            str(lines_file),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["appended_lines"] == 2

    content = (group_dir / "2026-04-29.md").read_text()
    assert content.count("- 10:") == 2


def test_non_monotonic_append_still_writes_and_warns(group_dir):
    # Existing tail is 09:13; new line is 02:54 — earlier. Helper
    # appends anyway (clock skew between containers is normal) and
    # flags monotonic=false plus a stderr note.
    daily = group_dir / "2026-04-29.md"
    daily.write_text("# Daily Summary — 2026-04-29\n" "- 09:13 UTC — out of order anchor\n")

    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "2026-04-29",
            "--line",
            "- 02:54 UTC — earlier than tail",
        ]
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["monotonic"] is False
    assert "non-monotonic" in proc.stderr

    # The append still happened — we don't drop entries on clock skew.
    assert "- 02:54 UTC — earlier than tail\n" in daily.read_text()


def test_trusted_target_writes_to_trusted_dir(trusted_dir, group_dir):
    # Provide both --group-daily and --trusted-daily so the helper
    # cannot accidentally write to the production /workspace path; the
    # `--target trusted` flag must select the trusted dir.
    proc = _run_cli(
        [
            "--target",
            "trusted",
            "--group-daily",
            str(group_dir),
            "--trusted-daily",
            str(trusted_dir),
            "--date",
            "2026-04-29",
            "--line",
            "- 11:00 UTC [test-source] — cross-group entry",
        ]
    )
    assert proc.returncode == 0, proc.stderr

    assert (trusted_dir / "2026-04-29.md").exists()
    assert not (group_dir / "2026-04-29.md").exists()


def test_concurrent_appends_do_not_lose_lines(group_dir):
    # Spawn two subprocesses appending different lines to the same
    # daily file simultaneously. Both lines must be present in the
    # final file — the breaking shape `LOCK_EX` is meant to prevent.
    args_common = [
        sys.executable,
        str(SCRIPT_PATH),
        "--target",
        "group",
        "--group-daily",
        str(group_dir),
        "--date",
        "2026-04-29",
    ]

    procs = [
        subprocess.Popen(
            args_common + ["--line", f"- 12:0{i} UTC — concurrent writer {i}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for i in range(2)
    ]
    for p in procs:
        out, err = p.communicate(timeout=10)
        assert p.returncode == 0, err.decode()

    content = (group_dir / "2026-04-29.md").read_text()
    assert "concurrent writer 0" in content
    assert "concurrent writer 1" in content


def test_missing_line_and_lines_file_is_cli_error(group_dir):
    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
        ]
    )
    assert proc.returncode != 0
    # argparse mutually-exclusive-required prints to stderr.
    assert "--line" in proc.stderr or "--lines-file" in proc.stderr


def test_invalid_date_is_cli_error(group_dir):
    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "not-a-date",
            "--line",
            "- 09:00 UTC — never written",
        ]
    )
    assert proc.returncode != 0
    assert "invalid --date" in proc.stderr


def test_unreadable_lines_file_exits_2_with_diagnostic(group_dir, tmp_path):
    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "2026-04-29",
            "--lines-file",
            str(tmp_path / "does-not-exist.txt"),
        ]
    )
    assert proc.returncode == 2
    assert "cannot read --lines-file" in proc.stderr


def test_non_utf8_lines_file_exits_2_not_traceback(group_dir, tmp_path):
    # `--lines-file` advertises UTF-8 input. A binary blob caught the
    # bare `except OSError` only, which let UnicodeDecodeError bubble
    # up as a traceback + rc=1, violating the "exit 2 / stdout clean"
    # contract.
    bad = tmp_path / "binary.txt"
    bad.write_bytes(b"\xff\xfe not valid utf-8")
    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "2026-04-29",
            "--lines-file",
            str(bad),
        ]
    )
    assert proc.returncode == 2
    assert "not valid UTF-8" in proc.stderr
    assert proc.stdout == ""


def test_non_utf8_existing_daily_file_exits_2_not_traceback(group_dir):
    # Manual edit / corruption of the daily file with non-UTF-8 bytes
    # should produce a clean exit 2 rather than a traceback.
    daily = group_dir / "2026-04-29.md"
    daily.write_bytes(b"\xff\xfe corrupt header")
    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "2026-04-29",
            "--line",
            "- 09:00 UTC — never appended",
        ]
    )
    assert proc.returncode == 2
    assert "not valid UTF-8" in proc.stderr
    assert proc.stdout == ""


def test_non_monotonic_detected_when_later_line_in_batch_is_earliest(group_dir, tmp_path):
    # Existing tail is 09:00; batch is [09:30, 02:54] — the second
    # entry is earlier than the tail. Pre-fix code only checked the
    # first batch entry and reported `monotonic: true`; post-fix
    # checks the earliest entry and flags it.
    daily = group_dir / "2026-04-29.md"
    daily.write_text("# Daily Summary — 2026-04-29\n- 09:00 UTC — anchor\n")

    lines_file = tmp_path / "batch.txt"
    lines_file.write_text("- 09:30 UTC — first new\n- 02:54 UTC — earliest in batch\n")

    proc = _run_cli(
        [
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--date",
            "2026-04-29",
            "--lines-file",
            str(lines_file),
        ]
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["monotonic"] is False
    assert "non-monotonic" in proc.stderr


def test_default_date_is_today_utc(group_dir, monkeypatch):
    # Direct in-process call (not subprocess) so we can monkeypatch
    # the helper's `utc_today` and assert default-date behavior
    # without depending on the wall clock.
    module = load_script("append_daily_default_date", SCRIPT_REL)
    monkeypatch.setattr(module, "utc_today", lambda: dt.date(2026, 4, 29))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "append-to-daily-log.py",
            "--target",
            "group",
            "--group-daily",
            str(group_dir),
            "--line",
            "- 09:00 UTC — default-date entry",
        ],
    )
    with pytest.raises(SystemExit) as ei:
        module.main()
    assert ei.value.code == 0
    assert (group_dir / "2026-04-29.md").exists()


# ------------- in-process unit tests -------------


@pytest.fixture
def helper(monkeypatch):
    return load_script("append_daily_helper", SCRIPT_REL)


def test_last_entry_minutes_handles_mixed_lines(helper):
    text = (
        "# Daily Summary — 2026-04-29\n"
        "## 12:00 UTC — heading not a bullet\n"
        "- 09:13 UTC — first bullet\n"
        "random freeform note\n"
        "- 11:30 UTC — last bullet\n"
    )
    assert helper.last_entry_minutes(text) == 11 * 60 + 30


def test_last_entry_minutes_returns_none_when_no_bullets(helper):
    assert helper.last_entry_minutes("# Daily Summary — 2026-04-29\n") is None


def test_min_entry_minutes_finds_earliest_in_batch(helper):
    # Out-of-order batch — the monotonic check needs the earliest
    # entry, not the first one in input order. A `[09:00, 02:54]`
    # batch appended after `08:00` is non-monotonic because of the
    # second entry; checking only the first would miss it.
    lines = [
        "freeform line",
        "- 09:00 UTC — late",
        "- 02:54 UTC — early — earliest in batch",
        "- 11:00 UTC — even later",
    ]
    assert helper.min_entry_minutes(lines) == 2 * 60 + 54


def test_min_entry_minutes_returns_none_when_no_bullets(helper):
    assert helper.min_entry_minutes(["freeform", ""]) is None


def test_line_count_handles_no_trailing_newline(helper):
    # Manually-edited daily files sometimes lack the trailing
    # newline; line_count must still report the legal final line.
    assert helper.line_count("a\nb\nc") == 3
    assert helper.line_count("a\nb\nc\n") == 3
    assert helper.line_count("") == 0


def test_atomic_write_preserves_existing_mode(helper, tmp_path):
    target = tmp_path / "target.md"
    target.write_text("orig\n")
    os.chmod(target, 0o640)

    helper.atomic_write_text(target, "new content\n")

    assert target.read_text() == "new content\n"
    assert (target.stat().st_mode & 0o777) == 0o640


def test_atomic_write_creates_with_default_mode(helper, tmp_path):
    target = tmp_path / "fresh.md"
    helper.atomic_write_text(target, "first write\n")

    assert target.read_text() == "first write\n"
    # Default 0o644; the actual mode on disk is also affected by the
    # process umask, so check the bits the helper explicitly set.
    actual = target.stat().st_mode & 0o777
    assert actual & 0o600 == 0o600


def test_append_lines_no_op_for_empty_input(helper, tmp_path):
    daily = tmp_path / "2026-04-29.md"
    daily.write_text("# Daily Summary — 2026-04-29\n- 09:00 UTC — anchor\n")
    result = helper.append_lines(daily, [], dt.date(2026, 4, 29))
    assert result["appended_lines"] == 0
    # The file is untouched.
    assert "anchor" in daily.read_text()
