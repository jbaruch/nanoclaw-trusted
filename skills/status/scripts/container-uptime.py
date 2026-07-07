#!/usr/bin/env python3
"""Compute container uptime from /.dockerenv mtime.

`/.dockerenv` is created by Docker at container spawn time and is
present in every container regardless of trust tier (untrusted,
trusted, main), so this script is safe to call from any cross-tier
skill that needs container start time.

Output (single-line JSON to stdout):
    {"uptime_text": "<Nd Hh (since ISO8601)>", "started": "<ISO8601 UTC>"}
                            on success
    {"uptime_text": "unknown", "started": null}
                            when /.dockerenv is missing (e.g. running
                            on a dev host outside a container)

Exit codes:
    0 — success path: container present (`/.dockerenv` exists) OR the
        expected non-container environment (missing `/.dockerenv`,
        signalled via `started: null` in the JSON payload).
    >0 — unexpected error (e.g. permissions, OS-level fault). The
        Python traceback propagates to stderr per
        `jbaruch/coding-policy: error-handling`; we do NOT swallow
        unexpected exceptions.

Stderr is unused on the happy path.
"""
import datetime
import json
import os
import sys


DOCKERENV_PATH = "/.dockerenv"


def compute_uptime(now: datetime.datetime) -> dict:
    """Pure function — takes 'now' as input so tests can pin time."""
    try:
        epoch = os.path.getmtime(DOCKERENV_PATH)
    except FileNotFoundError:
        return {"uptime_text": "unknown", "started": None}
    started_dt = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
    started = started_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    age = now - started_dt
    uptime_text = f"{age.days}d {age.seconds // 3600}h (since {started})"
    return {"uptime_text": uptime_text, "started": started}


def main() -> int:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = compute_uptime(now)
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
