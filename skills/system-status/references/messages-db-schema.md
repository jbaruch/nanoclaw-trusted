# messages.db Schema Inventory

Lookup data for `rules/messages-db-schema.md`, which owns query, mutation, and drift requirements. The inventory lists known columns, not every later host addition. Live `PRAGMA table_info(<table>)` shows the mounted shape.

## Tables and lookup values

- **`registered_groups`**: `jid`, `name`, `folder`, `trigger_pattern`, `added_at`, `container_config`, `requires_trigger`, `is_main`. `container_config` JSON holds `trusted`.
- **`chats`**: `jid`, `name`, `last_message_time`, `channel`, `is_group`.
- **`messages`**: `id`, `chat_jid`, `sender`, `sender_name`, `content`, `timestamp`, `is_from_me`, `is_bot_message`, `reply_to_message_id`, `reply_to_message_content`, `reply_to_sender_name`, `telegram_message_id`.
- **`scheduled_tasks`**: `id`, `group_folder`, `chat_jid`, `prompt`, `schedule_type`, `schedule_value`, `next_run`, `last_run`, `last_result`, `status`, `created_at`, `context_mode`, `script`, `created_by_role`, `schedule_timezone`, `continuation_cycle_id`, `session_id`, `source`.
- **`tz_state`**: `id`, `current_tz`, `home_tz`, `scheduler_tz`, `schema_version`, `segments`, `last_stale_warning_at`.
- **`follow_me_tasks`**: `name` (PK), `local_time`, `schedule_value`, `last_run_date`, `pending_run_at`, `schema_version`, `updated_at`.
- **`phase_completions`**: `phase` (PK), `last_completed`, `metadata`, `updated_at`, `schema_version`.
- **`sessions`**: `group_folder`, `session_name` (default `'default'`), `session_id`.
- **`task_run_logs`**: `id` (PK autoincrement), `task_id` (FK → `scheduled_tasks.id`), `run_at`, `duration_ms`, `status`, `result`, `error`. Observed `status` values: `success`, `error`, `killed`, `precheck_skipped`.

## Runtime owner and schema of record

The `jbaruch/nanoclaw` host orchestrator owns this database and all schema changes. Source evidence below is pinned to host commit `ef8cf4d6837427f8924deda83b7af00c215996fc`; check the running host's revision before assuming a newer shape.

- Legacy runtime tables: `chats`, `messages`, `scheduled_tasks`, `task_run_logs`, `sessions`, `registered_groups`. [src/db.ts `createSchema`](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/db.ts#L109) initializes them. Its inline upgrades add columns, rebuild `task_run_logs` for cascading deletes, and rebuild `sessions` for the composite key. [`initDatabase`](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/db.ts#L549) calls `createSchema` then `applyStateMigrations`. These legacy tables have no per-record version guarantee.
- Versioned state tables: `phase_completions` is initialized by [state-009-phase-completions.ts](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/state-migrations/state-009-phase-completions.ts); `tz_state` and `follow_me_tasks` by [state-010-tz-state.ts](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/state-migrations/state-010-tz-state.ts). Subsequent timezone changes are `state-012-tz-state-segments.ts`, `state-013-tz-state-segments-datetime.ts`, and `state-015-tz-state-stale-warning.ts` in that directory. The [migration registry](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/state-migrations/index.ts) is authoritative for ordered upgrades, including later additions to legacy tables.

## Shipped readers

| Reader | Required tables and fields | Current behavior |
|---|---|---|
| `skills/system-status/scripts/system-status-checks.py` | `scheduled_tasks`: `id`, `prompt`, `next_run`, `status`; `messages`: table exists for `COUNT(*)`, no particular column; `task_run_logs`: `task_id`, `run_at`, `status`, `result`, `error` | Host-wide health inspection. Nullable `next_run` is not due; failure summaries use `error`, then `result`, then empty string. Each failed query emits its alert plus one shared stderr Python/PRAGMA remediation; its fields are unavailable, not empty. Exit 1 only when every query fails. |
| `skills/trusted-memory/scripts/register-session.py` | `sessions`: `group_folder`, `session_name`, `session_id`; composite key (`group_folder`, `session_name`) | Opens the existing database with URI `mode=ro` and selects by both nonempty `NANOCLAW_GROUP_FOLDER` and `NANOCLAW_SESSION_NAME`. Missing identity, no matching row, or SQLite errors yield `None` and an actionable stderr diagnostic. Both the per-session state entry and legacy mirror receive that scoped ID or null. |

The host's [`nativeContextEnv` and `sdkContextEnv`](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/container/agent-runner/src/native-context-env.ts#L83-L113) supply group/session identity to skill subprocesses; the host supplies `default` for an unnamed session. The [host-wide `sessions` table](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/db.ts#L255-L260) can contain multiple groups and named sessions; an unscoped `LIMIT 1` can return another session's ID.

Restore that runtime context when identity is unavailable; check host session registration when no row matches, or the mount and schema when SQLite fails. The state entry's `default` label when the session name is unset is a bootstrap compatibility label, not evidence of database identity. Bootstrap state/sentinel writes confirm memory bootstrap, not a successful database lookup; a null session ID remains unavailable evidence.

Both readers open the existing database with URI `mode=ro` and `uri=True`; neither creates a replacement database if the mount disappears before connection. The other inventory tables are not queried by either shipped reader.

## Mounted schema inspection

The standalone `sqlite3` CLI is absent. This inspection command opens the existing database read-only:

```bash
python3 -c 'import sqlite3; c = sqlite3.connect("file:/workspace/store/messages.db?mode=ro", uri=True); print(c.execute("PRAGMA table_info(scheduled_tasks)").fetchall())'
```
