# trusted-memory state schema (state-006, #298)

State written by `scripts/register-session.py` per `jbaruch/coding-policy: stateful-artifacts`. Owner skill is `tessl__trusted-memory`. Reader skills (`heartbeat-precheck.py`, `check-email` upstream) treat any unrecognised `schema_version` as "no usable prior state" and let the next owner-skill run rewrite it.

Post-`jbaruch/nanoclaw#298` the storage is two SQLite tables in `/workspace/store/messages.db`. The JSON-era `session-state.json` envelope retires, and so does the `fcntl.LOCK_EX + tempfile + fsync + os.replace` ceremony that defended it.

## Tables

### `trusted_sessions`

Per-session metadata. PK on `session_name` makes per-session writes atomic — the `default` session and the `maintenance` session cannot clobber each other's columns.

| Column           | Type    | Nullable | Default             | Notes                                  |
| ---------------- | ------- | -------- | ------------------- | -------------------------------------- |
| `session_name`   | TEXT    | no       | —                   | PK; e.g. `default`, `maintenance`      |
| `session_id`     | TEXT    | yes      | NULL                | from `messages.db.sessions`; nullable when SDK call hasn't completed yet |
| `started`        | TEXT    | no       | —                   | UTC `Z`-suffixed ISO; cycle timestamp  |
| `epoch`          | INTEGER | no       | —                   | Unix seconds at write time             |
| `last_seen`      | TEXT    | no       | —                   | UTC `Z`-suffixed ISO; bumped on each register-session run + each heartbeat-precheck cycle |
| `schema_version` | INTEGER | no       | `1`                 | Bumped on shape change; owner migrates |

### `trusted_session_singleton`

Single-row store for fields that aren't per-session: the back-compat `active_session_id` mirror and the JSON-blob payload columns owned by the default-session writer (`pending_response`, `muted_threads` — opaque to the schema, read/written verbatim by the owner).

| Column              | Type    | Nullable | Default | Notes                                  |
| ------------------- | ------- | -------- | ------- | -------------------------------------- |
| `id`                | INTEGER | no       | —       | PK with `CHECK(id = 1)` — singleton    |
| `active_session_id` | TEXT    | yes      | NULL    | Top-level back-compat mirror; written by `register-session.py` |
| `pending_response`  | TEXT    | yes      | NULL    | JSON blob; default-session writer owns |
| `muted_threads`     | TEXT    | yes      | NULL    | JSON blob; default-session writer owns |
| `schema_version`    | INTEGER | no       | `1`     | Bumped on shape change                 |

## Writer contracts

`register-session.py` UPSERTs both tables in a single SQL transaction:

```sql
BEGIN;
  INSERT INTO trusted_sessions
    (session_name, session_id, started, epoch, last_seen)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(session_name) DO UPDATE SET
      session_id = excluded.session_id,
      started    = excluded.started,
      epoch      = excluded.epoch,
      last_seen  = excluded.last_seen;
  INSERT INTO trusted_session_singleton (id, active_session_id)
    VALUES (1, ?)
    ON CONFLICT(id) DO UPDATE SET active_session_id = excluded.active_session_id;
COMMIT;
```

The singleton UPSERT deliberately omits `pending_response` and `muted_threads` — those columns belong to the default-session writer; preserve any value already there. The CHECK(id=1) constraint makes the table genuinely single-row; an accidental `id=2` insert fails loudly with a constraint violation.

## Reader contracts

`heartbeat-precheck.py` Section 5 / 5a stamp `last_seen` on the per-session row:

```sql
UPDATE trusted_sessions
   SET last_seen = ?     -- now UTC ISO-Z
 WHERE session_name = ?;
```

PK on `session_name` makes the UPDATE atomic; sibling sessions are physically untouched.

Per `coding-policy: stateful-artifacts`, reader skills don't migrate row shapes. On encountering an unfamiliar `schema_version`, a reader treats the row as "no usable prior state" and falls through to its safe default. Only the owner skill (`register-session.py`) bumps `schema_version`; readers stay version-locked until the owner ships an upgraded write.

## Concurrency

The post-`#298` SQLite shape replaces the JSON-era `session-state.json.lock` sidecar entirely. SQLite's WAL + RESERVED-lock semantics serialise concurrent writers; the per-row PKs (`session_name` on `trusted_sessions`, `id` on the singleton) prevent cross-row clobber.

Writers from other tables (`tz_state`, `follow_me_tasks`, `phase_completions`, `email_state`, `email_seen_ids`, `resumable_cycles`) target their own rows; sibling-table interference is impossible.

## Bootstrap sentinel

The `/tmp/session_bootstrapped` file remains file-based — it's a per-container sentinel, not shared state, so SQLite isn't the right tool. The atomic-write recipe (tempfile in same dir → flush → fsync → chmod-preserve → `os.replace`) for the sentinel is preserved in `register-session.py`. `needs-bootstrap.py` reads it via `open()` as before.

## Migration policy

- `schema_version` columns bump on every shape change.
- Only `register-session.py` migrates row shapes.
- Schema-level changes ship as a new state-NNN migration in `src/state-migrations/` upstream, with a corresponding bump to the relevant `schema_version` default.
