#!/usr/bin/env python3
"""Write session metadata and optionally mark a completed bootstrap.

Usage:
    register-session.py [--registration-only]

Scheduled wakes pass --registration-only after the task skill. This updates
session metadata without reading or writing the bootstrap sentinel.

Reads:
    - Session ID from `/workspace/store/messages.db`, opened read-only.
      `sessions` is keyed by (`group_folder`, `session_name`) — see
      `/home/node/.claude/skills/tessl__system-status/references/messages-db-schema.md`.
    - `$NANOCLAW_GROUP_FOLDER` and `$NANOCLAW_SESSION_NAME` must both be
      nonempty for the database lookup. Missing identity, no matching row,
      or SQLite errors yield `None` with an actionable stderr diagnostic.
      The output state entry defaults to `default` if the session name is unset.
    - Current bootstrap session ID from `session_identity.py`; the lookup
      contract is in `state-schema.md`.

Writes (both atomically, tempfile + fsync + os.replace):
    - `/workspace/group/session-state.json` — updates
      `sessions.<session_name>` with `{started, epoch, session_id,
      last_seen}` and mirrors `session_id` at the top level for
      back-compat.
    - `/tmp/session_bootstrapped` — sentinel containing the current
      resolved Claude session ID so `needs-bootstrap.py` reports "done" on
      subsequent runs. Left untouched with --registration-only. NOT written
      when both identity variables are missing
      or empty — an empty sentinel would match an empty env on the
      next run and cause bootstrap to be skipped forever.

Exit codes:
    0 — success (state written; sentinel skipped is still success
        with --registration-only, or when the resolved identity is empty
        with a stderr note)
    1 — state file read/write failure
    2 — invalid command-line arguments

Database lookup failure does not abort memory bootstrap. State and the
back-compat mirror record `None`; successful writes and the sentinel
confirm bootstrap completion, not database availability. Never create or
repair the runtime-owned database here.

Concurrency: state-file writes use an fcntl.LOCK_EX on
`<STATE_PATH>.lock` around the read-modify-write cycle. Other
writers on this file must take the same lock; without coordination
a concurrent update can clobber this script's `sessions.<name>`
write.
"""
import argparse
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
from session_identity import current_session_id  # noqa: E402

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
    group_folder = os.environ.get("NANOCLAW_GROUP_FOLDER")
    session_name = os.environ.get("NANOCLAW_SESSION_NAME")
    if not group_folder or not session_name:
        print(
            "register-session: session_id unavailable; NANOCLAW_GROUP_FOLDER and "
            "NANOCLAW_SESSION_NAME must both be nonempty. Run through the host runtime "
            "so it supplies the group and session identity.",
            file=sys.stderr,
        )
        return None
    try:
        conn = sqlite3.connect(
            Path(MESSAGES_DB).resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=MESSAGES_DB_TIMEOUT_SECONDS,
        )
        try:
            row = conn.execute(
                "SELECT session_id FROM sessions WHERE group_folder = ? AND session_name = ?",
                (group_folder, session_name),
            ).fetchone()
        finally:
            conn.close()
        if row:
            return row[0]
        print(
            f"register-session: session_id unavailable for group {group_folder!r}, "
            f"session {session_name!r} in {MESSAGES_DB}. "
            "Check the host sessions registration for this identity.",
            file=sys.stderr,
        )
        return None
    except sqlite3.Error as e:
        print(
            f"register-session: session_id unavailable from {MESSAGES_DB}: {e}. "
            "Check the host messages.db mount and sessions schema; do not create a replacement.",
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


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registration-only",
        action="store_true",
        help="Update session metadata without marking bootstrap complete",
    )
    args = parser.parse_args(argv)
    session_id = read_session_id_from_db()
    session_name = os.environ.get("NANOCLAW_SESSION_NAME", "default")
    claude_session_id = current_session_id()

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
        # Closing the fd releases the flock; no explicit LOCK_UN needed.
        lock_f.close()

    if args.registration_only:
        emit_status(session_id, session_name, wrote_sentinel=False)
        return

    # Both callers use one resolver. Missing identity must leave bootstrap
    # required instead of stamping an empty sentinel that could match forever.
    if not claude_session_id:
        print(
            "register-session: set CLAUDE_SESSION_ID or use Claude Code's CLAUDE_CODE_SESSION_ID; "
            "both are missing/empty, so the sentinel is skipped and the next run re-bootstraps",
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
