---
alwaysApply: false
applyTo: "** — when querying messages.db or referencing its column names"
---

# messages.db Schema

## Inspect before selecting columns

- Use Python `sqlite3` with URI `file:/workspace/store/messages.db?mode=ro` and `uri=True` for reads; the standalone `sqlite3` CLI is absent.
- Before selecting columns, read the installed inventory: `/home/node/.claude/skills/tessl__system-status/references/messages-db-schema.md`.
- Check live `PRAGMA table_info(<table>)`; never guess column names.
- Use `trigger_pattern`, not `trigger_word` or `trigger`.
- `registered_groups` uses `jid`, not `chat_jid`; `trusted` lives in `container_config` JSON.
- `last_result` belongs to `scheduled_tasks`; `task_run_logs` uses `status`, `result`, `error`.

## Keys and comparisons

- `messages` has composite PK (`id`, `chat_jid`).
- `sessions` has composite PK (`group_folder`, `session_name`). Scope session lookups by both host-supplied `NANOCLAW_GROUP_FOLDER` and `NANOCLAW_SESSION_NAME`; missing identity means unavailable, never an arbitrary row.
- `tz_state` is a singleton (`id = 1`); other PKs and lookup values are in the inventory.
- Compare `task_run_logs.run_at` against matching ISO-8601 `T`/`Z` strings, never SQLite `datetime(...)` output.

## Mutations

- Prefer MCP host tools exposing the field (`chat_status`, `inspect_gate_decisions`, `get_scheduled_tasks`) over raw SQL.
- Direct SQL is for read-mostly inspection; mutate only when concurrency is provably safe.
- `follow_me_tasks` writes require `BEGIN IMMEDIATE` per `nanoclaw-admin: follow-me-two-phase-lock`.

## Schema drift

- If live PRAGMA differs from the inventory, update the reference in lock-step with the host schema change; never guess the new shape.
