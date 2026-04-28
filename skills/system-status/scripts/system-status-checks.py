#!/usr/bin/env python3
"""Read-only system-status probe for trusted-tier NanoClaw containers.

Trusted containers see the orchestrator's SQLite at
`/workspace/store/messages.db`. This script collects the three
read-only health signals the trusted skill surfaces — stuck
scheduled tasks, DB size, recent task-run failures — and emits one
JSON payload the SKILL.md consumes.

It is the trusted-tier counterpart to admin's `heartbeat-checks.py`,
narrowed to the data sources trusted containers actually have:

- Trusted tier does NOT have the disk-/IPC-/container-health probes
  (those live in admin and require admin-only mounts).
- Trusted tier does NOT manage the dismiss file
  (`/workspace/group/system-health-dismissed.json`); that's an admin
  responsibility. This script reports task-run failures verbatim;
  the operator decides what to do with them.

Per `jbaruch/coding-policy: script-delegation`: the deterministic
SQL queries belong here, not inlined in the SKILL.md prose. The
previous `tessl__check-system-health` skill in trusted had three
`python3 -c` blocks; this script replaces them.

Per `jbaruch/coding-policy: testing-standards`: covered by
`tests/test_system_status_checks.py` in this tile.

Usage:
    system-status-checks.py [--db <path>] [--stuck-grace-minutes <int>]
                            [--message-row-warn <int>]
                            [--task-log-row-warn <int>]
                            [--db-size-mb-warn <int>]

    --db                   Path to the messages.db (default
                           `/workspace/store/messages.db`).
    --stuck-grace-minutes  How long past `next_run` an active task
                           must be to count as stuck. Default 5.
                           Mirrors the prior inline check.
    --message-row-warn     Alert threshold for `messages` row count.
                           Default 100000 (the prior inline value).
    --task-log-row-warn    Alert threshold for `task_run_logs` row
                           count. Default 10000.
    --db-size-mb-warn      Alert threshold for the SQLite file size
                           in MB. Default 500.

Output (single-line JSON on stdout):
    {
      "checked_at": "<ISO 8601 UTC>",
      "db_path": "...",
      "stuck_tasks": [
        {"id": "task-...", "prompt_preview": "...", "next_run": "..."}
      ],
      "stuck_count": <int>,
      "row_counts": {"messages": <int>, "task_run_logs": <int>},
      "db_size_mb": <float>,
      "recent_failures": [
        {"task_id": "...", "run_at": "...", "error_summary": "..."}
      ],
      "alerts": [<short string>]   // one per crossed threshold
    }

Exit codes:
    0 — checks ran (alerts may or may not be populated; absence of
        alerts means silence per the SKILL.md output contract).
    1 — DB unreachable or every check raised: stdout still emits
        the canonical shape with `alerts` describing what failed,
        so the SKILL.md can report uniformly.
    2 — CLI usage error.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _query_stuck_tasks(conn: sqlite3.Connection, grace_minutes: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, substr(prompt, 1, 50), next_run "
        "FROM scheduled_tasks "
        "WHERE status = 'active' AND next_run <= datetime('now', ?)",
        (f"-{int(grace_minutes)} minutes",),
    ).fetchall()
    return [
        {"id": r[0], "prompt_preview": r[1], "next_run": r[2]} for r in rows
    ]


def _query_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    logs = conn.execute("SELECT COUNT(*) FROM task_run_logs").fetchone()[0]
    return {"messages": msgs, "task_run_logs": logs}


def _query_recent_failures(conn: sqlite3.Connection) -> list[dict]:
    """Failures within the last 24h. The dismiss file lives in admin's
    domain and is NOT consulted here; trusted reports verbatim and
    the operator decides what to do (per the SKILL.md contract)."""
    rows = conn.execute(
        "SELECT task_id, run_at, substr(coalesce(last_result, ''), 1, 200) "
        "FROM task_run_logs "
        "WHERE run_at >= datetime('now', '-24 hours') "
        "  AND coalesce(last_result, '') LIKE '%error%' "
        "ORDER BY run_at DESC "
        "LIMIT 20"
    ).fetchall()
    return [
        {"task_id": r[0], "run_at": r[1], "error_summary": r[2]} for r in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default="/workspace/store/messages.db")
    parser.add_argument("--stuck-grace-minutes", type=int, default=5)
    parser.add_argument("--message-row-warn", type=int, default=100_000)
    parser.add_argument("--task-log-row-warn", type=int, default=10_000)
    parser.add_argument("--db-size-mb-warn", type=int, default=500)
    args = parser.parse_args()

    payload: dict = {
        "checked_at": _now_iso(),
        "db_path": args.db,
        "stuck_tasks": [],
        "stuck_count": 0,
        "row_counts": {"messages": None, "task_run_logs": None},
        "db_size_mb": None,
        "recent_failures": [],
        "alerts": [],
    }

    if not os.path.exists(args.db):
        payload["alerts"].append(f"db missing: {args.db}")
        print(json.dumps(payload))
        return 1

    try:
        payload["db_size_mb"] = round(os.path.getsize(args.db) / 1048576, 1)
    except OSError as e:
        payload["alerts"].append(f"db size unreadable: {e}")

    conn = None
    try:
        conn = sqlite3.connect(args.db, timeout=5)
        try:
            payload["stuck_tasks"] = _query_stuck_tasks(
                conn, args.stuck_grace_minutes
            )
            payload["stuck_count"] = len(payload["stuck_tasks"])
        except sqlite3.Error as e:
            payload["alerts"].append(f"stuck-tasks query failed: {e}")
        try:
            payload["row_counts"] = _query_row_counts(conn)
        except sqlite3.Error as e:
            payload["alerts"].append(f"row-counts query failed: {e}")
        try:
            payload["recent_failures"] = _query_recent_failures(conn)
        except sqlite3.Error as e:
            payload["alerts"].append(f"recent-failures query failed: {e}")
    except sqlite3.Error as e:
        payload["alerts"].append(f"db connect failed: {e}")
        print(json.dumps(payload))
        return 1
    finally:
        if conn is not None:
            conn.close()

    if payload["stuck_count"] > 0:
        payload["alerts"].append(f"stuck tasks: {payload['stuck_count']}")
    msg_rows = payload["row_counts"].get("messages")
    if msg_rows is not None and msg_rows > args.message_row_warn:
        payload["alerts"].append(
            f"messages rowcount {msg_rows} > {args.message_row_warn}"
        )
    log_rows = payload["row_counts"].get("task_run_logs")
    if log_rows is not None and log_rows > args.task_log_row_warn:
        payload["alerts"].append(
            f"task_run_logs rowcount {log_rows} > {args.task_log_row_warn}"
        )
    if (
        payload["db_size_mb"] is not None
        and payload["db_size_mb"] > args.db_size_mb_warn
    ):
        payload["alerts"].append(
            f"db size {payload['db_size_mb']}MB > {args.db_size_mb_warn}MB"
        )
    if payload["recent_failures"]:
        payload["alerts"].append(
            f"recent task failures: {len(payload['recent_failures'])} in last 24h"
        )

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
