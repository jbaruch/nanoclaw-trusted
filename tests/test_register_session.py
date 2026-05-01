"""Tests for skills/trusted-memory/scripts/register-session.py.

Post-#298 contract:
  - Reads session_id from messages.db `sessions` table (best-effort)
  - UPSERTs trusted_sessions row keyed on session_name
  - UPSERTs trusted_session_singleton (id=1) for the back-compat
    `active_session_id` mirror — does NOT touch pending_response /
    muted_threads (default-session writer owns those columns)
  - Sentinel write skipped on empty $CLAUDE_SESSION_ID
  - Emits single-line JSON status to stdout
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/trusted-memory/scripts/register-session.py"


def _seed_db(db_path, session_id):
    """Create messages.db with state-006 schema + the orchestrator's
    `sessions` table (which register-session reads, not writes)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE sessions (session_id TEXT);
            CREATE TABLE trusted_sessions (
              session_name   TEXT PRIMARY KEY,
              session_id     TEXT,
              started        TEXT NOT NULL,
              epoch          INTEGER NOT NULL,
              last_seen      TEXT NOT NULL,
              schema_version INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE trusted_session_singleton (
              id                INTEGER PRIMARY KEY CHECK(id = 1),
              active_session_id TEXT,
              pending_response  TEXT,
              muted_threads     TEXT,
              schema_version    INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        if session_id is not None:
            conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def register_session(tmp_path, monkeypatch):
    db_path = tmp_path / "messages.db"
    sentinel = tmp_path / "session_bootstrapped"
    module = load_script(f"register_session_{tmp_path.name}", SCRIPT_REL)
    monkeypatch.setattr(module, "DB_PATH", str(db_path))
    monkeypatch.setattr(module, "SENTINEL", str(sentinel))
    return module, db_path, sentinel


def _run(module, capsys):
    rc = None
    try:
        rc = module.main()
    except SystemExit as e:
        rc = e.code
    captured = capsys.readouterr()
    out = captured.out.strip()
    payload = json.loads(out.splitlines()[-1]) if out else None
    return rc, payload, captured.err


def _trusted_session(db_path, session_name):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT session_id, started, epoch, last_seen FROM trusted_sessions "
            "WHERE session_name = ?",
            (session_name,),
        ).fetchone()
    finally:
        conn.close()


def _singleton(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT active_session_id, pending_response, muted_threads "
            "FROM trusted_session_singleton WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()


def test_full_roundtrip(register_session, monkeypatch, capsys):
    module, db_path, sentinel = register_session
    _seed_db(db_path, "db-session-42")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-99")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, payload, _ = _run(module, capsys)
    assert rc == 0
    assert payload == {
        "session_id": "db-session-42",
        "session_name": "default",
        "schema_version": 1,
        "wrote_state": True,
        "wrote_sentinel": True,
    }
    row = _trusted_session(db_path, "default")
    assert row[0] == "db-session-42"  # session_id
    assert row[2] > 0  # epoch
    singleton = _singleton(db_path)
    assert singleton[0] == "db-session-42"  # active_session_id
    assert sentinel.read_text() == "claude-session-99"


def test_missing_claude_session_id_skips_sentinel(register_session, monkeypatch, capsys):
    module, db_path, sentinel = register_session
    _seed_db(db_path, "db-session-7")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, payload, _ = _run(module, capsys)
    assert rc == 0
    assert payload["wrote_state"] is True
    assert payload["wrote_sentinel"] is False
    assert _trusted_session(db_path, "default") is not None
    assert not sentinel.exists()


def test_empty_sessions_table_records_none(register_session, monkeypatch, capsys):
    """When messages.db has no `sessions` row yet, session_id is None
    in the trusted_sessions row but the row is still inserted."""
    module, db_path, _ = register_session
    _seed_db(db_path, None)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "x")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "maintenance")

    rc, payload, _ = _run(module, capsys)
    assert rc == 0
    assert payload["session_id"] is None
    assert _trusted_session(db_path, "maintenance")[0] is None


def test_sibling_session_rows_untouched(register_session, monkeypatch, capsys):
    """A 'default' UPSERT must not touch a pre-existing 'maintenance'
    row — the JSON-era cross-session clobber bug retires by
    construction with PK on session_name."""
    module, db_path, _ = register_session
    _seed_db(db_path, "db-session-42")
    # Pre-existing maintenance row with a session_id that should
    # survive the default-session call below.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO trusted_sessions "
            "(session_name, session_id, started, epoch, last_seen) "
            "VALUES ('maintenance', 'maint-id', '2026-04-29T00:00:00Z', 1, "
            "'2026-04-29T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("CLAUDE_SESSION_ID", "x")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")
    _run(module, capsys)
    # Maintenance row is pristine:
    maint = _trusted_session(db_path, "maintenance")
    assert maint[0] == "maint-id"
    # Default row was inserted:
    default = _trusted_session(db_path, "default")
    assert default[0] == "db-session-42"


def test_singleton_preserves_pending_response(register_session, monkeypatch, capsys):
    """The default-session writer owns `pending_response` /
    `muted_threads` columns. register-session.py only writes
    `active_session_id`; pre-existing values in the other columns
    must survive the UPSERT."""
    module, db_path, _ = register_session
    _seed_db(db_path, "db-session-42")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO trusted_session_singleton "
            "(id, active_session_id, pending_response, muted_threads) "
            "VALUES (1, 'old-active', 'baruch is asking', '[\"thread-a\"]')"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("CLAUDE_SESSION_ID", "x")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")
    _run(module, capsys)

    singleton = _singleton(db_path)
    assert singleton[0] == "db-session-42"  # active_session_id updated
    assert singleton[1] == "baruch is asking"  # pending_response preserved
    assert singleton[2] == '["thread-a"]'  # muted_threads preserved


def test_db_unreachable_exits_1(register_session, monkeypatch, capsys):
    """A DB that doesn't exist OR has no trusted_* tables → exit 1."""
    module, db_path, _ = register_session
    # Don't seed — db_path doesn't exist.
    monkeypatch.setenv("CLAUDE_SESSION_ID", "x")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, _, err = _run(module, capsys)
    assert rc == 1
    assert "SQLite error" in err or "trusted" in err.lower()
