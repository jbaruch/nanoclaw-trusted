#!/usr/bin/env python3
"""Write session metadata into the trusted_sessions / trusted_session_
singleton SQLite tables and mark bootstrap done.

Usage:
    register-session.py

Reads:
    - Session ID from `/workspace/store/messages.db` (`sessions` table,
      first row). Falls back to `None` when the table is empty.
    - Session name from `$NANOCLAW_SESSION_NAME` (defaults to `default`).
    - Current session ID from `$CLAUDE_SESSION_ID` (for the bootstrap
      sentinel).

Writes (single SQLite transaction + sentinel file):
    - `trusted_sessions` row keyed on `session_name` (UPSERT) with
      `{started, epoch, session_id, last_seen}`.
    - `trusted_session_singleton` (id=1, UPSERT) with
      `active_session_id` mirrored at the top level for back-compat.
    - `/tmp/session_bootstrapped` sentinel containing the current
      CLAUDE_SESSION_ID so `needs-bootstrap.py` reports "done" on
      subsequent runs. NOT written when CLAUDE_SESSION_ID is missing
      or empty — an empty sentinel would match an empty env on the
      next run and cause bootstrap to be skipped forever.

Replaces the JSON-era `session-state.json` envelope read-modify-write
that this script defended with `fcntl.LOCK_EX` + tempfile + fsync +
`os.replace`. The PK on `session_name` makes per-session writes
atomic — a concurrent writer for `default` and `maintenance` cannot
clobber each other's columns. Sibling readers (heartbeat-precheck's
last_seen stamp, check-email's seen-ids append) target their own
tables; cross-writer interference is impossible by construction.

Exit codes:
    0 — success (state written; sentinel skipped is still success
        when CLAUDE_SESSION_ID is empty/unset, with a stderr note)
    1 — DB / SQL / sentinel write failure (diagnostic on stderr)

Note on sqlite behavior: the script catches `sqlite3.Error` from the
`sessions` read broadly and treats it as `session_id=None` — a
deliberate relaxation, not a behavior-preserving port, because
bootstrap shouldn't hard-crash the whole memory-load flow when the
DB is temporarily unreadable (locked, early-boot, etc.). The trusted
state UPSERT below uses the same DB connection and DOES exit 1 on
failure — that's the load-bearing write.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

# messages.db can be locked by the orchestrator's writer during bootstrap;
# without a timeout sqlite3.connect waits forever. Other admin-tile
# scripts (heartbeat-precheck / heartbeat-checks) use 5–15s. 10s keeps
# the bootstrap flow responsive while still riding out short contention.
MESSAGES_DB_TIMEOUT_SECONDS = 10

DB_PATH = os.environ.get("ORDERS_DB_PATH", "/workspace/store/messages.db")
SENTINEL = "/tmp/session_bootstrapped"

# Bumped when the row shapes change; coordinated with state-006-trusted-
# session-state.ts upstream.
TRUSTED_SCHEMA_VERSION = 1


def read_session_id_from_db(conn: sqlite3.Connection) -> Optional[str]:
    """Best-effort read of the orchestrator's current session_id."""
    try:
        row = conn.execute("SELECT session_id FROM sessions LIMIT 1").fetchone()
        return row[0] if row else None
    except sqlite3.Error as e:
        print(
            f"register-session: cannot read session_id from sessions table: {e}",
            file=sys.stderr,
        )
        return None


def atomic_write_text(path: str, content: str, default_mode: int = 0o644) -> None:
    """Atomically replace `path`'s contents with `content`. Used only
    for the `/tmp/session_bootstrapped` sentinel — the trusted state
    is now in SQLite and uses a SQL transaction, not a file."""
    dir_ = os.path.dirname(path) or "."
    try:
        target_mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        target_mode = default_mode

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_, delete=False, suffix=".tmp"
        ) as tf:
            tmp_path = tf.name
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())
        os.chmod(tmp_path, target_mode)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError as e:
                print(
                    f"register-session: failed to clean up temp file {tmp_path}: {e}",
                    file=sys.stderr,
                )


def main() -> int:
    session_name = os.environ.get("NANOCLAW_SESSION_NAME", "default")
    claude_session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    epoch = int(time.time())

    # Hard-fail when the orchestrator DB is absent rather than letting
    # `sqlite3.connect()` create an empty file (which would then error
    # out on missing tables and leave a stray DB file behind). A
    # missing DB points at the orchestrator's state-006 migration not
    # having run; the operator needs that visible, not masked.
    if not os.path.exists(DB_PATH):
        print(
            f"register-session: orchestrator DB not found at {DB_PATH}. "
            "Verify the database file exists; if missing, the state-006 "
            "migration may not have run.",
            file=sys.stderr,
        )
        return 1

    conn = None
    session_id: Optional[str] = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=MESSAGES_DB_TIMEOUT_SECONDS)
        session_id = read_session_id_from_db(conn)

        with conn:
            # UPSERT the per-session row. PK on session_name makes this
            # write atomic; sibling sessions (e.g. 'default' vs
            # 'maintenance') are physically untouched. `schema_version`
            # is written on both insert and update so a future bump of
            # TRUSTED_SCHEMA_VERSION self-heals existing rows on the
            # next register-session call (the alternative — only on
            # insert — would leave older rows at the prior version
            # forever, defeating the "owner bumps schema_version"
            # contract in state-schema.md).
            conn.execute(
                """
                INSERT INTO trusted_sessions
                  (session_name, session_id, started, epoch, last_seen, schema_version)
                  VALUES (?, ?, ?, ?, ?, ?)
                  ON CONFLICT(session_name) DO UPDATE SET
                    session_id     = excluded.session_id,
                    started        = excluded.started,
                    epoch          = excluded.epoch,
                    last_seen      = excluded.last_seen,
                    schema_version = excluded.schema_version
                """,
                (
                    session_name,
                    session_id,
                    now_iso,
                    epoch,
                    now_iso,
                    TRUSTED_SCHEMA_VERSION,
                ),
            )
            # UPSERT the singleton (id=1) with the back-compat
            # `active_session_id` mirror. The CHECK(id=1) constraint
            # makes the table genuinely single-row. `pending_response`
            # and `muted_threads` are NOT in the column list — the
            # default-session writer owns those columns; preserve any
            # value already there. `schema_version` self-heals via the
            # same pattern as `trusted_sessions` above.
            conn.execute(
                """
                INSERT INTO trusted_session_singleton (id, active_session_id, schema_version)
                  VALUES (1, ?, ?)
                  ON CONFLICT(id) DO UPDATE SET
                    active_session_id = excluded.active_session_id,
                    schema_version    = excluded.schema_version
                """,
                (session_id, TRUSTED_SCHEMA_VERSION),
            )
    except sqlite3.Error as e:
        print(
            f"register-session: SQLite error writing trusted state at {DB_PATH}: {e}",
            file=sys.stderr,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()

    # Refuse to write an empty sentinel. An empty string would match the
    # default `$CLAUDE_SESSION_ID` fallback in needs-bootstrap.py
    # (`os.environ.get(..., "")`), so a subsequent run would read an
    # empty sentinel, see an empty current session, and incorrectly
    # decide bootstrap was already done — permanently skipping memory
    # load for every future session until the file is removed.
    if not claude_session_id:
        print(
            "register-session: $CLAUDE_SESSION_ID missing/empty; skipping sentinel write so next run re-bootstraps",
            file=sys.stderr,
        )
        emit_status(session_id, session_name, wrote_sentinel=False)
        return 0

    try:
        atomic_write_text(SENTINEL, claude_session_id)
    except OSError as e:
        print(
            f"register-session: failed to write sentinel {SENTINEL}: {e}",
            file=sys.stderr,
        )
        # The DB transaction has already committed — emit status
        # before exiting so callers expecting structured stdout can
        # still see what was registered. The exit code remains the
        # authoritative success signal.
        emit_status(session_id, session_name, wrote_sentinel=False)
        return 1

    emit_status(session_id, session_name, wrote_sentinel=True)
    return 0


def emit_status(
    session_id: Optional[str], session_name: str, *, wrote_sentinel: bool
) -> None:
    """Single-line JSON status to stdout per `script-delegation` rule.

    Always prints on a successful state write. `wrote_state` is always true
    here because reaching this point implies the atomic state write
    succeeded; failure paths exit non-zero before getting here. The exit
    code remains the authoritative success signal — JSON is for callers
    that want to log/inspect what was registered."""
    print(
        json.dumps(
            {
                "session_id": session_id,
                "session_name": session_name,
                "schema_version": TRUSTED_SCHEMA_VERSION,
                "wrote_state": True,
                "wrote_sentinel": wrote_sentinel,
            }
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
