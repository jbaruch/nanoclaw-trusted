---
name: system-status
description: Read-only system-status probe for trusted-tier NanoClaw containers — surfaces stuck scheduled tasks, DB size, and recent task-run failures from the orchestrator's SQLite at `/workspace/store/messages.db`. Use as part of heartbeat or standalone. Triggers on "system status", "check tasks", "stuck tasks", "database size", "task failures".
---

# System Status

**Process steps in order. Do not skip ahead.**

Read-only counterpart to admin's `tessl__heartbeat`'s system-health probe. Trusted tier sees the orchestrator's SQLite directly but does not have admin's filesystem / IPC / container mounts and does not manage the dismiss file at `/workspace/group/system-health-dismissed.json`.

## Step 1 — Run the probe

```bash
python3 /home/node/.claude/skills/tessl__system-status/scripts/system-status-checks.py
```

Output is a single JSON object on stdout: `{checked_at, db_path, stuck_tasks, stuck_count, row_counts, db_size_mb, recent_failures, alerts}`. Exit 0 = checks ran (alerts may or may not be populated). Exit 1 = DB unreachable or every check raised; the JSON still emits with `alerts` describing what failed.

## Step 2 — Act on the result

Parse the JSON.

- `alerts` is empty → silent success. **Output nothing.**
- `alerts` is non-empty → report via `mcp__nanoclaw__send_message`. Include the items the alert refers to: `stuck_tasks` IDs + prompt previews, `recent_failures` task IDs + error summaries, the offending row counts or DB size.

The DB is read-only from the trusted container — auto-fix is not possible. The orchestrator's scheduler retries stuck tasks on the next poll; if alerts persist across cycles, flag for the operator.

## What this skill is NOT

- It does not modify the DB.
- It does not consult or write `/workspace/group/system-health-dismissed.json`. That file is admin's domain (per `tessl__heartbeat`'s system-health step). Trusted reports verbatim; the operator decides what to do.
- It does not probe filesystem / IPC / container health. Those checks require admin-only mounts and live in admin's `heartbeat-checks.py`.
