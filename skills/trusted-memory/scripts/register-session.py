#!/usr/bin/env python3
"""Write session metadata into session-state.json and mark bootstrap done.

Usage:
    register-session.py

Reads:
    - Session ID from `/workspace/store/messages.db` (`sessions` table,
      first row). Falls back to `None` when the table is empty.
    - Session name from `$NANOCLAW_SESSION_NAME` (defaults to `default`).
    - Current session ID from `$CLAUDE_SESSION_ID` (for the bootstrap
      sentinel).

Writes (both atomically, tempfile + fsync + os.replace):
    - `/workspace/group/session-state.json` — updates
      `sessions.<session_name>` with `{started, epoch, session_id,
      last_seen}` and mirrors `session_id` at the top level for
      back-compat.
    - `/tmp/session_bootstrapped` — sentinel containing the current
      CLAUDE_SESSION_ID so `needs-bootstrap.py` reports "done" on
      subsequent runs. NOT written when CLAUDE_SESSION_ID is missing
      or empty — an empty sentinel would match an empty env on the
      next run and cause bootstrap to be skipped forever.

Exit codes:
    0 — success (state written; sentinel skipped is still success
        when CLAUDE_SESSION_ID is empty/unset, with a stderr note)
    1 — state file read/write failure

Note on sqlite behavior: the previous inline block would have raised
on a missing messages.db or missing `sessions` table. This script
intentionally catches `sqlite3.Error` broadly and treats it as
`session_id=None` with a stderr note — a deliberate relaxation,
not a behavior-preserving port, because bootstrap shouldn't hard-
crash the whole memory-load flow when the DB is temporarily
unreadable (locked, early-boot, etc.). The back-compat mirror still
records `None`, which downstream consumers tolerate.

Concurrency: state-file writes use an fcntl.LOCK_EX on
`<STATE_PATH>.lock` around the read-modify-write cycle. heartbeat-
precheck.py and check-email writers use the same lock file; without
coordination a concurrent `last_seen` stamp or `pending_response`
update can clobber this script's `sessions.<name>` write.
"""
import fcntl
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

MESSAGES_DB = "/workspace/store/messages.db"
STATE_PATH = "/workspace/group/session-state.json"
STATE_LOCK_PATH = STATE_PATH + ".lock"
SENTINEL = "/tmp/session_bootstrapped"


def read_session_id_from_db() -> Optional[str]:
    try:
        conn = sqlite3.connect(MESSAGES_DB, timeout=MESSAGES_DB_TIMEOUT_SECONDS)
        try:
            row = conn.execute(
                "SELECT session_id FROM sessions LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except sqlite3.Error as e:
        print(
            f"register-session: cannot read session_id from {MESSAGES_DB}: {e}",
            file=sys.stderr,
        )
        return None


def atomic_write_text(path: str, content: str, default_mode: int = 0o644) -> None:
    """Atomically replace `path`'s contents with `content`.

    Tempfile in the same directory → write → flush → fsync → chmod (to
    the target's existing mode, or `default_mode` if creating fresh) →
    os.replace. Cleans up the tempfile on any failure so a crash mid-
    write doesn't leave a stray `*.tmp` orphan next to the target.

    The chmod step matters: NamedTemporaryFile defaults to 0600, which
    would silently narrow shared state files (e.g. /workspace/group/*)
    on the first write unless preserved.
    """
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


def atomic_write_json(path: str, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2))


def main() -> None:
    session_id = read_session_id_from_db()
    session_name = os.environ.get("NANOCLAW_SESSION_NAME", "default")
    claude_session_id = os.environ.get("CLAUDE_SESSION_ID", "")

    # Hold LOCK_EX on STATE_LOCK_PATH for the entire read-modify-write
    # cycle. Other writers on this file — heartbeat-precheck's
    # last_seen stamp, check-email's seen_email_ids append, default-
    # session pending_response/muted_threads updates — use (or will
    # use) the same lock file. Without coordination, our sessions.<name>
    # write can clobber a concurrent last_seen update, or vice versa.
    # heartbeat-precheck.py documents the shared-lock convention.
    try:
        lock_f = open(STATE_LOCK_PATH, "a+")
    except OSError as e:
        print(
            f"register-session: cannot open lock file {STATE_LOCK_PATH}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)

        try:
            with open(STATE_PATH) as f:
                state = json.load(f)
        except FileNotFoundError:
            state = {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # UnicodeDecodeError covers non-UTF-8 bytes (corruption/manual
            # edit); treated like malformed JSON — start fresh with a
            # stderr note rather than letting a traceback bubble up.
            print(
                f"register-session: state file malformed at {STATE_PATH}: {e}; starting fresh",
                file=sys.stderr,
            )
            state = {}
        except OSError as e:
            # PermissionError, EIO, etc. — docstring promises exit 1 on
            # any read failure.
            print(
                f"register-session: state file read failed at {STATE_PATH}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

        if not isinstance(state, dict):
            print(
                f"register-session: state file at {STATE_PATH} contained non-object JSON (type {type(state).__name__}); starting fresh",
                file=sys.stderr,
            )
            state = {}

        # setdefault("sessions", {}) doesn't guard against an existing but
        # non-dict value (e.g. list/string) — state["sessions"][name] = ...
        # below would crash with TypeError. Reset to {} with a stderr note
        # if the shape is wrong.
        if not isinstance(state.get("sessions"), dict):
            if "sessions" in state:
                print(
                    f"register-session: state.sessions was not an object (type {type(state.get('sessions')).__name__}); resetting",
                    file=sys.stderr,
                )
            state["sessions"] = {}
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state["sessions"][session_name] = {
            "started": now_iso,
            "epoch": int(time.time()),
            "session_id": session_id,
            "last_seen": now_iso,
        }
        state["session_id"] = session_id  # back-compat; see PR #55

        try:
            atomic_write_json(STATE_PATH, state)
        except OSError as e:
            print(
                f"register-session: failed to write {STATE_PATH}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)
    finally:
        # Lock released automatically when lock_f closes, but be
        # explicit so the intent is obvious to readers.
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        except OSError:
            # Already released or fd invalidated — lock_f.close() below
            # handles the rest. Nothing actionable; skip the stderr.
            pass
        lock_f.close()

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
        return

    try:
        atomic_write_text(SENTINEL, claude_session_id)
    except OSError as e:
        print(
            f"register-session: failed to write sentinel {SENTINEL}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
