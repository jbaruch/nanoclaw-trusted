#!/usr/bin/env python3
"""Write session metadata into session-state.json and mark bootstrap done.

Usage:
    register-session.py

Reads:
    - Session ID from `/workspace/store/messages.db` (`sessions` table,
      first row). Falls back to `None` when the table is empty.
      `sessions` is keyed by (`group_folder`, `session_name`) — see
      `rules/messages-db-schema.md`; the single-row assumption behind
      "first row" is documented at the query site below.
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
`<STATE_PATH>.lock` around the read-modify-write cycle. Other
writers on this file must take the same lock; without coordination
a concurrent update can clobber this script's `sessions.<name>`
write.
"""
import fcntl
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Sibling `memory_write` module — see the matching block in
# `append-to-daily-log.py` for why sys.path needs explicit help when
# the script is loaded via importlib (tests) or its hyphenated CLI
# filename.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from memory_write import write_atomic  # noqa: E402

# messages.db can be locked by the orchestrator's writer during bootstrap;
# without a timeout sqlite3.connect waits forever. 10s keeps the bootstrap
# flow responsive while still riding out short contention.
MESSAGES_DB_TIMEOUT_SECONDS = 10

MESSAGES_DB = "/workspace/store/messages.db"
STATE_PATH = "/workspace/group/session-state.json"
STATE_LOCK_PATH = STATE_PATH + ".lock"
SENTINEL = "/tmp/session_bootstrapped"

# Bumped when the on-disk shape of session-state.json changes. v1 is the
# current canonical shape (top-level `schema_version` + `sessions.<name>`
# subtree + back-compat top-level `session_id`). Files written before
# this field existed are read-tolerated below and silently upgraded to
# v1 on the next write — owner-skill migration per
# `jbaruch/coding-policy: stateful-artifacts`.
STATE_SCHEMA_VERSION = 1


def read_session_id_from_db() -> Optional[str]:
    try:
        conn = sqlite3.connect(MESSAGES_DB, timeout=MESSAGES_DB_TIMEOUT_SECONDS)
        try:
            # `sessions` is keyed by (group_folder, session_name), one
            # row per group session (rules/messages-db-schema.md). The
            # host currently writes a single row — the main group's
            # session, which is the container this script runs in — so
            # a bare LIMIT 1 is deterministic today. If the host starts
            # registering sessions for other groups, this query must
            # gain a WHERE on this container's group_folder; there is
            # no container-side way to derive that folder name yet.
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


def atomic_write_json(path: str, data: dict) -> None:
    """Thin wrapper that serializes `data` and delegates to the shared
    `memory_write.write_atomic`. The atomic-write recipe (tempfile →
    flush → fsync → chmod → os.replace, with mode preserved across
    overwrites) lives in `memory_write.py` so every trusted-memory
    writer uses the same implementation."""
    write_atomic(Path(path), json.dumps(data, indent=2))


def main() -> None:
    session_id = read_session_id_from_db()
    session_name = os.environ.get("NANOCLAW_SESSION_NAME", "default")
    claude_session_id = os.environ.get("CLAUDE_SESSION_ID", "")

    # Hold LOCK_EX on STATE_LOCK_PATH for the entire read-modify-write
    # cycle. Other writers on this file must use the same lock; without
    # coordination, our sessions.<name> write can clobber a concurrent
    # update, or vice versa.
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
        # Stamp schema_version last so it always reflects what this writer
        # produces, even when starting from an unversioned legacy file.
        state["schema_version"] = STATE_SCHEMA_VERSION

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
        emit_status(session_id, session_name, wrote_sentinel=False)
        return

    try:
        write_atomic(Path(SENTINEL), claude_session_id)
    except OSError as e:
        print(
            f"register-session: failed to write sentinel {SENTINEL}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    emit_status(session_id, session_name, wrote_sentinel=True)


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
                "schema_version": STATE_SCHEMA_VERSION,
                "wrote_state": True,
                "wrote_sentinel": wrote_sentinel,
            }
        )
    )


if __name__ == "__main__":
    main()
