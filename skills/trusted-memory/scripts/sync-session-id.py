#!/usr/bin/env python3
"""Sync the current session_id from the messages DB into
/workspace/group/session-state.json.

Why a script (per `docs/tile-plugin-audit.md` §4):
- More than 10 lines of non-trivial logic if done correctly (lock,
  atomic write, mode preservation, read-back).
- State-machine mutation on a multi-writer file (`session-state.json`
  is also written by `heartbeat-precheck`, `register-session`,
  `append-seen-ids`, plus default-session pending_response /
  muted_threads paths per §8 concurrency registry).
- Correctness hazards the reader can't audit by eye — if the inline
  block does plain `open('w')` + `json.dump`, a SIGTERM mid-write
  truncates the file and breaks every other reader.

Lock convention per §8 registry:
  fcntl.LOCK_EX on `/workspace/group/session-state.json.lock`

Atomic write per §5 contract:
  tempfile (same dir) → write → flush → fsync → chmod (preserve) →
  os.replace → read-back verification.

Output (stdout): single-line JSON
  `{"session_id": "<id-or-null>", "wrote": <bool>}`.
  - `wrote=true` means the state file was rewritten this call.
  - `wrote=false` means the value was already current (no-op).
Diagnostic on stderr on failure.

Exit codes:
  0 — wrote successfully (or no-op when DB has no session row).
  1 — runtime failure: DB unavailable, JSON corrupt + unrecoverable,
      lock acquisition failed, write failed, read-back mismatch.
  2 — usage error (no args expected; reject extra argv to surface
      caller bugs early per §5/§7).
"""
import fcntl
import json
import os
import sqlite3
import sys
import tempfile
from typing import Optional

DB_PATH = '/workspace/store/messages.db'
STATE_PATH = '/workspace/group/session-state.json'
LOCK_PATH = STATE_PATH + '.lock'


def read_current_session_id() -> Optional[str]:
    """Return the session_id from the first row of `sessions`, or None
    if the DB is empty / missing the table. DB errors propagate to the
    caller as `sqlite3.Error` (caught in main with the documented
    exit-1 contract)."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    try:
        row = conn.execute(
            'SELECT session_id FROM sessions LIMIT 1'
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def load_state() -> dict:
    """Read the existing state file. Treat missing or corrupt as
    {} — the writer always rewrites the full file, so we don't need
    to preserve unparseable bytes."""
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            sys.stderr.write(
                f"sync-session-id: {STATE_PATH} is not a JSON object "
                f"(type={type(data).__name__}); treating as empty\n"
            )
            return {}
        return data
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        sys.stderr.write(
            f"sync-session-id: state load failed ({type(exc).__name__}: "
            f"{exc}); treating as empty\n"
        )
        return {}


def atomic_write(state: dict) -> None:
    """Atomic-write per §5: tempfile in the same dir → flush → fsync
    → chmod (preserve mode if target exists, default 0o644 otherwise)
    → os.replace → read-back verify. Caller holds the lock; this
    helper does NOT acquire it."""
    state_dir = os.path.dirname(STATE_PATH)
    os.makedirs(state_dir, exist_ok=True)

    # Capture target mode BEFORE writing so we preserve it across replace.
    try:
        mode = os.stat(STATE_PATH).st_mode & 0o777
    except FileNotFoundError:
        mode = 0o644

    tmp = tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        dir=state_dir,
        prefix='.session-state-',
        suffix='.tmp',
        delete=False,
    )
    tmp_path = tmp.name
    try:
        json.dump(state, tmp, indent=2, ensure_ascii=False, sort_keys=True)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, STATE_PATH)
        tmp_path = None  # consumed by replace; cleanup loop must not unlink
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError as exc:
                sys.stderr.write(
                    f"sync-session-id: tmp cleanup failed for "
                    f"{tmp_path}: {type(exc).__name__}: {exc}\n"
                )

    # Read-back verification per §5: re-open + json.load. Exit loudly
    # on corruption so the caller doesn't ship a broken state file.
    with open(STATE_PATH, 'r', encoding='utf-8') as f:
        round_trip = json.load(f)
    if round_trip != state:
        raise RuntimeError(
            "sync-session-id: read-back mismatch — written state does "
            "not match in-memory state"
        )


def main() -> int:
    if len(sys.argv) > 1:
        sys.stderr.write(
            "sync-session-id: takes no arguments; got "
            f"{sys.argv[1:]!r}\nUsage: sync-session-id.py\n"
        )
        return 2

    try:
        session_id = read_current_session_id()
    except sqlite3.Error as exc:
        sys.stderr.write(
            f"sync-session-id: DB read failed: "
            f"{type(exc).__name__}: {exc}\n"
        )
        return 1

    # Acquire the §8-registry lock on session-state.json.lock so we
    # don't race with heartbeat-precheck / register-session writes.
    # The lock file is opened outside the with-block on purpose:
    # `flock` is process-scoped and the lock-fd must outlive the
    # critical section.
    try:
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        lock_fd = open(LOCK_PATH, 'w', encoding='utf-8')
    except OSError as exc:
        sys.stderr.write(
            f"sync-session-id: can't open lock at {LOCK_PATH}: "
            f"{type(exc).__name__}: {exc}\n"
        )
        return 1

    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except OSError as exc:
            # `flock` itself can fail (interrupted syscall, resource
            # limits) per §5 "OSError catch around fcntl.flock".
            sys.stderr.write(
                f"sync-session-id: flock failed on {LOCK_PATH}: "
                f"{type(exc).__name__}: {exc}\n"
            )
            return 1

        state = load_state()
        # Skip the rewrite if the file already carries the current
        # session_id — saves a fsync/replace round-trip on the common
        # idempotent-call path. The atomic-write contract still fires
        # whenever there's an actual change.
        wrote = state.get('session_id') != session_id
        if wrote:
            state['session_id'] = session_id
            try:
                atomic_write(state)
            except (OSError, RuntimeError) as exc:
                # OSError covers ENOSPC, EACCES, fsync, replace failures.
                # RuntimeError is the read-back-mismatch path.
                sys.stderr.write(
                    f"sync-session-id: write failed for {STATE_PATH}: "
                    f"{type(exc).__name__}: {exc}\n"
                )
                return 1
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            # Unlock failure means we lose the lock anyway when the
            # process exits — log and move on rather than mask the
            # primary error path.
            pass
        lock_fd.close()

    print(json.dumps({"session_id": session_id, "wrote": wrote}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
