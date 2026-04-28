"""Baseline tests for skills/system-status/scripts/system-status-checks.py.

Locks down the documented contract per `coding-policy:
testing-standards`:

- stdout is single-line JSON with the documented field set.
- exit codes: 0 success (with or without alerts), 1 hard DB
  failure, 2 CLI usage error.
- threshold crossings populate `alerts`; silence (empty alerts
  array) is the success signal the SKILL.md keys on.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/system-status/scripts/system-status-checks.py"


@pytest.fixture
def system_status_checks():
    """Fresh-loaded module under test per call so any shell-state /
    argparse / sys.argv leakage between tests is avoided."""
    return load_script("system_status_checks_under_test", SCRIPT_REL)


def _build_test_db(path) -> None:
    """Create a minimal `messages.db` with the schema the probe queries.
    Tests populate rows via `_seed_*` helpers per scenario."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE messages (id INTEGER PRIMARY KEY, ts TEXT);
        CREATE TABLE task_run_logs (
            task_id TEXT,
            run_at TEXT,
            last_result TEXT
        );
        CREATE TABLE scheduled_tasks (
            id TEXT PRIMARY KEY,
            prompt TEXT,
            status TEXT,
            next_run TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _run(module, monkeypatch, capsys, *args):
    """main() returns an int (0/1) on its own paths and raises
    SystemExit only on the argparse usage-error path (exit 2). Capture
    both shapes so the helper handles every documented exit code."""
    monkeypatch.setattr("sys.argv", ["system-status-checks.py", *args])
    try:
        rc = module.main()
        code = 0 if rc is None else int(rc)
    except SystemExit as exc:
        code = 0 if exc.code is None else int(exc.code)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_db_missing_returns_exit_1_with_alert(system_status_checks, monkeypatch, capsys, tmp_path):
    """Missing DB is a hard failure — exit 1, but the JSON shape stays
    consistent so the SKILL.md can report uniformly."""
    code, out, _ = _run(
        system_status_checks, monkeypatch, capsys, "--db", str(tmp_path / "missing.db")
    )
    payload = json.loads(out)
    assert code == 1
    assert payload["alerts"] == [f"db missing: {tmp_path / 'missing.db'}"]
    assert payload["stuck_tasks"] == []
    assert payload["recent_failures"] == []


def test_clean_db_emits_silent_success(system_status_checks, monkeypatch, capsys, tmp_path):
    """Empty DB, no rows past thresholds → empty `alerts`, exit 0."""
    db = tmp_path / "messages.db"
    _build_test_db(db)
    code, out, _ = _run(system_status_checks, monkeypatch, capsys, "--db", str(db))
    payload = json.loads(out)
    assert code == 0
    assert payload["alerts"] == []
    assert payload["stuck_count"] == 0
    assert payload["row_counts"] == {"messages": 0, "task_run_logs": 0}
    assert payload["recent_failures"] == []


def test_stuck_task_crosses_grace_window(system_status_checks, monkeypatch, capsys, tmp_path):
    db = tmp_path / "messages.db"
    _build_test_db(db)
    conn = sqlite3.connect(str(db))
    past = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO scheduled_tasks VALUES ('task-1', 'long prompt text here', 'active', ?)",
        (past,),
    )
    conn.commit()
    conn.close()

    code, out, _ = _run(system_status_checks, monkeypatch, capsys, "--db", str(db))
    payload = json.loads(out)
    assert code == 0
    assert payload["stuck_count"] == 1
    assert payload["stuck_tasks"][0]["id"] == "task-1"
    assert any("stuck tasks: 1" in a for a in payload["alerts"])


def test_recent_task_failure_within_24h(system_status_checks, monkeypatch, capsys, tmp_path):
    db = tmp_path / "messages.db"
    _build_test_db(db)
    conn = sqlite3.connect(str(db))
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO task_run_logs VALUES ('task-fail-1', ?, 'fatal error: timeout reached')",
        (recent,),
    )
    conn.commit()
    conn.close()

    code, out, _ = _run(system_status_checks, monkeypatch, capsys, "--db", str(db))
    payload = json.loads(out)
    assert code == 0
    assert len(payload["recent_failures"]) == 1
    assert payload["recent_failures"][0]["task_id"] == "task-fail-1"
    assert any("recent task failures" in a for a in payload["alerts"])


def test_old_task_failure_outside_24h_window_is_excluded(
    system_status_checks, monkeypatch, capsys, tmp_path
):
    db = tmp_path / "messages.db"
    _build_test_db(db)
    conn = sqlite3.connect(str(db))
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO task_run_logs VALUES ('task-old', ?, 'error: gone')",
        (old,),
    )
    conn.commit()
    conn.close()

    code, out, _ = _run(system_status_checks, monkeypatch, capsys, "--db", str(db))
    payload = json.loads(out)
    assert code == 0
    assert payload["recent_failures"] == []


def test_message_rowcount_above_threshold_alerts(
    system_status_checks, monkeypatch, capsys, tmp_path
):
    db = tmp_path / "messages.db"
    _build_test_db(db)
    conn = sqlite3.connect(str(db))
    # Use the test's own override flag to keep the seed small but still
    # exceed the cap — running 100k inserts in a fixture would slow tests.
    for i in range(15):
        conn.execute("INSERT INTO messages VALUES (?, ?)", (i, "2026-04-28"))
    conn.commit()
    conn.close()

    code, out, _ = _run(
        system_status_checks,
        monkeypatch,
        capsys,
        "--db",
        str(db),
        "--message-row-warn",
        "10",
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["row_counts"]["messages"] == 15
    assert any("messages rowcount 15" in a for a in payload["alerts"])


def test_db_size_above_threshold_alerts(system_status_checks, monkeypatch, capsys, tmp_path):
    """Inflate the test DB enough that its size in MB rounds up past
    0.0 (so a `0 MB` threshold strictly fires). Seeding ~80 KB of
    messages rows is enough to push round(size/1048576, 1) to 0.1."""
    db = tmp_path / "messages.db"
    _build_test_db(db)
    conn = sqlite3.connect(str(db))
    long_ts = "2026-04-28T00:00:00Z" + ("x" * 1000)
    for i in range(100):
        conn.execute("INSERT INTO messages VALUES (?, ?)", (i, long_ts))
    conn.commit()
    conn.close()
    code, out, _ = _run(
        system_status_checks,
        monkeypatch,
        capsys,
        "--db",
        str(db),
        "--db-size-mb-warn",
        "0",
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["db_size_mb"] is not None and payload["db_size_mb"] > 0
    assert any("db size" in a and "MB > 0MB" in a for a in payload["alerts"])
