"""Baseline tests for skills/trusted-memory/scripts/register-session.py.

Covers the documented contract:
  - Reads session_id from /workspace/store/messages.db (sqlite3); tolerates
    sqlite errors as session_id=None rather than crashing.
  - Atomically writes session-state.json (sessions.<name> + back-compat
    top-level session_id + schema_version).
  - Atomically writes /tmp/session_bootstrapped sentinel — UNLESS
    $CLAUDE_SESSION_ID is empty, in which case sentinel is skipped to
    avoid a permanent bootstrap-skipped lockout.
  - Emits a single-line JSON status to stdout per script-delegation rule.
"""

import json
import sqlite3

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/trusted-memory/scripts/register-session.py"


def _make_messages_db(path, session_id):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE sessions (session_id TEXT)")
    if session_id is not None:
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.commit()
    conn.close()


@pytest.fixture
def register_session(tmp_path, monkeypatch):
    """Fresh module per test with all I/O paths redirected into tmp_path.
    Caller is responsible for populating messages.db (or leaving it
    missing for the sqlite-error path)."""
    messages_db = tmp_path / "messages.db"
    state_path = tmp_path / "session-state.json"
    sentinel = tmp_path / "session_bootstrapped"

    module = load_script(f"register_session_{tmp_path.name}", SCRIPT_REL)
    monkeypatch.setattr(module, "MESSAGES_DB", str(messages_db))
    monkeypatch.setattr(module, "STATE_PATH", str(state_path))
    monkeypatch.setattr(module, "STATE_LOCK_PATH", str(state_path) + ".lock")
    monkeypatch.setattr(module, "SENTINEL", str(sentinel))

    return module, messages_db, state_path, sentinel


def _run_and_capture(module, capsys):
    """Run main(); return (exit_code or None, parsed_json_or_None)."""
    rc = None
    try:
        module.main()
    except SystemExit as e:
        rc = e.code
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured.splitlines()[-1]) if captured else None
    return rc, payload


def test_full_roundtrip_writes_state_and_sentinel(register_session, monkeypatch, capsys):
    module, messages_db, state_path, sentinel = register_session
    _make_messages_db(messages_db, "db-session-42")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-99")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None  # main() returns normally on success, no SystemExit
    assert payload == {
        "session_id": "db-session-42",
        "session_name": "default",
        "schema_version": 1,
        "wrote_state": True,
        "wrote_sentinel": True,
    }
    state = json.loads(state_path.read_text())
    assert state["schema_version"] == 1
    assert state["session_id"] == "db-session-42"
    assert state["sessions"]["default"]["session_id"] == "db-session-42"
    assert sentinel.read_text() == "claude-session-99"


def test_missing_claude_session_id_skips_sentinel(register_session, monkeypatch, capsys):
    module, messages_db, state_path, sentinel = register_session
    _make_messages_db(messages_db, "db-session-7")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None
    assert payload["wrote_state"] is True
    assert payload["wrote_sentinel"] is False
    assert state_path.exists()
    assert not sentinel.exists()


def test_sqlite_error_falls_back_to_null_session_id(register_session, monkeypatch, capsys):
    module, messages_db, state_path, _sentinel = register_session
    # messages.db intentionally not created — sqlite3.connect() will
    # create an empty file, then the SELECT against a missing `sessions`
    # table raises sqlite3.OperationalError (a subclass of sqlite3.Error).
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-1")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None
    assert payload["session_id"] is None
    assert payload["wrote_state"] is True
    state = json.loads(state_path.read_text())
    assert state["sessions"]["default"]["session_id"] is None
    assert state["session_id"] is None


def test_legacy_unversioned_state_upgrades_to_v1(register_session, monkeypatch, capsys):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, "db-session-x")
    # Pre-existing legacy file (pre-PR jbaruch/nanoclaw#55 shape) has
    # only the top-level session_id and no `sessions` subtree, no
    # schema_version field.
    state_path.write_text(json.dumps({"session_id": "old-stamp"}))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-2")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    _run_and_capture(module, capsys)

    state = json.loads(state_path.read_text())
    assert state["schema_version"] == 1
    assert state["sessions"]["default"]["session_id"] == "db-session-x"
    # Top-level session_id is overwritten to current; legacy field
    # stays present for back-compat readers per state-schema.md.
    assert state["session_id"] == "db-session-x"


def test_corrupt_state_json_starts_fresh(register_session, monkeypatch, capsys):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, "db-session-y")
    state_path.write_text("not json at all {{")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-3")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "maintenance")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None
    assert payload["wrote_state"] is True
    state = json.loads(state_path.read_text())
    assert state["schema_version"] == 1
    assert "maintenance" in state["sessions"]
