---
alwaysApply: true
---

# messages.db Schema

## Don't Guess Column Names

The shared SQLite at `/workspace/store/messages.db` (accessed via `python3 -c 'import sqlite3; ...'` per the `cli-tools-not-installed` rule) has the tables below. `PRAGMA table_info(<table>)` confirms; values verified live on 2026-05-04. Recurring failure mode this rule closes: `no such column: trigger_word` / `chat_jid` / `trusted` errors (18 hits / 9 distinct guesses in observer-chat audit, 2026-04-28..05-03).

## Tables

- **`registered_groups`** (per-group config): `jid`, `name`, `folder`, `trigger_pattern`, `added_at`, `container_config`, `requires_trigger`, `is_main`. The `trigger_pattern` column is what callers sometimes guess as `trigger_word` or `trigger`. The `trusted` flag is NOT a column — it lives inside `container_config` JSON.
- **`chats`**: `jid`, `name`, `last_message_time`, `channel`, `is_group`.
- **`messages`**: `id`, `chat_jid`, `sender`, `sender_name`, `content`, `timestamp`, `is_from_me`, `is_bot_message`, `reply_to_message_id`, `reply_to_message_content`, `reply_to_sender_name`, `telegram_message_id`. Composite PK (`id`, `chat_jid`).
- **`scheduled_tasks`**: `id`, `group_folder`, `chat_jid`, `prompt`, `schedule_type`, `schedule_value`, `next_run`, `last_run`, `last_result`, `status`, `created_at`, `context_mode`, `script`, `created_by_role`, `schedule_timezone`, `continuation_cycle_id`, `session_id`, `source`.
- **`tz_state`** (singleton, `id = 1`): `id`, `current_tz`, `home_tz`, `scheduler_tz`, `schema_version`.
- **`follow_me_tasks`**: `name` (PK), `local_time`, `schedule_value`, `last_run_date`, `pending_run_at`, `schema_version`, `updated_at`.
- **`phase_completions`**: `phase` (PK), `last_completed`, `metadata`, `updated_at`, `schema_version`.

## Prefer MCP Tools for Mutations

Where an MCP host tool already exposes the field (`chat_status`, `inspect_gate_decisions`, `get_scheduled_tasks`, etc.), prefer it over raw SQL — the tool also handles the host-side concurrency contract (`BEGIN IMMEDIATE` for `follow_me_tasks` writes per the `nanoclaw-admin: follow-me-two-phase-lock` rule). Direct SQL is for read-mostly inspection; mutations should go through the tool path unless concurrency is provably safe.

## Schema Drift

If a `PRAGMA table_info` result diverges from the columns above, the host has shipped a state-migration not yet reflected in this rule. Update the rule in lock-step rather than guessing the new shape.
