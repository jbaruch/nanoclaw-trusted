#!/usr/bin/env python3
"""Check whether the current session needs memory bootstrap.

Usage:
    needs-bootstrap.py

Exit codes:
    0 — bootstrap IS needed (no sentinel, or sentinel points to a
        different session than `$CLAUDE_SESSION_ID`)
    1 — bootstrap NOT needed (sentinel matches current session)

The sentinel lives at `/tmp/session_bootstrapped` and stores the
session ID that last ran bootstrap. A new session within the same
container still triggers bootstrap — the sentinel is keyed per
session, not per container.
"""
import os
import sys

SENTINEL = "/tmp/session_bootstrapped"


def main() -> None:
    current = os.environ.get("CLAUDE_SESSION_ID", "")

    if not current:
        # Empty env cannot safely "match" a stored sentinel: if both are
        # empty the script would report "already bootstrapped" and skip
        # memory load forever. Treat empty env as bootstrap-needed.
        print(
            "needs-bootstrap: $CLAUDE_SESSION_ID missing/empty; defaulting to bootstrap-needed",
            file=sys.stderr,
        )
        sys.exit(0)

    try:
        with open(SENTINEL) as f:
            stored = f.read().strip()
    except FileNotFoundError:
        sys.exit(0)  # no sentinel → bootstrap needed
    except OSError as e:
        print(
            f"needs-bootstrap: cannot read sentinel at {SENTINEL}: {e}; assuming bootstrap needed",
            file=sys.stderr,
        )
        sys.exit(0)

    if not stored:
        # Defensive pair: an empty sentinel (shouldn't be written by
        # the fixed register-session.py, but could linger from pre-fix
        # runs or a manual touch) is treated as bootstrap-needed so we
        # self-heal rather than stay stuck.
        sys.exit(0)

    sys.exit(1 if stored == current else 0)


if __name__ == "__main__":
    main()
