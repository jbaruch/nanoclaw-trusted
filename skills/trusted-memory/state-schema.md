# trusted-memory state schema

State written by `scripts/register-session.py` per `jbaruch/coding-policy: stateful-artifacts`. Owner skill is `tessl__trusted-memory`. Reader skills (`heartbeat-precheck.py`, `check-email`) MUST treat any unrecognised shape as "no usable prior state" and let the next owner-skill run rewrite it.

## Files

### `/workspace/group/session-state.json`

Mutable JSON object. Per-group, not shared across containers.

```json
{
  "sessions": {
    "<NANOCLAW_SESSION_NAME>": {
      "started":    "<ISO-8601 UTC, e.g. 2026-04-27T15:00:00Z>",
      "epoch":      <int unix seconds>,
      "session_id": "<sqlite session_id from /workspace/store/messages.db, or null>",
      "last_seen":  "<ISO-8601 UTC>"
    }
  },
  "session_id": "<top-level mirror of the active session_id, back-compat>"
}
```

**Back-compat note (legacy migration, ex–`reference_session-state-migration.md`):** the top-level `session_id` field is the pre-`PR jbaruch/nanoclaw#55` shape, when only one session existed per group. It is still written so readers that haven't moved to the per-session subtree continue to work. New readers SHOULD use `sessions.<name>.session_id`. Old single-session files are accepted on read — register-session.py adds the `sessions` subtree without dropping the top-level field, so the migration is in-place and idempotent.

**Other writers on this file** must take `fcntl.LOCK_EX` on `/workspace/group/session-state.json.lock` for the duration of their read-modify-write cycle. Current writers documented in `nanoclaw-admin/skills/heartbeat/scripts/heartbeat-precheck.py`. Without the shared lock, concurrent updates clobber each other.

### `/tmp/session_bootstrapped`

Plain-text sentinel. One line: the value of `$CLAUDE_SESSION_ID` from the run that completed bootstrap.

`needs-bootstrap.py` compares this file's contents to the current `$CLAUDE_SESSION_ID`. Mismatch (or missing file) → bootstrap is needed. `register-session.py` REFUSES to write an empty sentinel because an empty value would match an empty env var on the next run and permanently suppress bootstrap.

## Schema versioning

Neither file currently carries a `schema_version` field — both shapes are stable enough that a bump hasn't been needed. When that changes, owner skill bumps and readers gain a guard per `stateful-artifacts.md`.
