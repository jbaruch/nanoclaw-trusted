# trusted-memory state schema

State written by `scripts/register-session.py` per `jbaruch/coding-policy: stateful-artifacts`. Owner skill is `tessl__trusted-memory`. Reader skills — `jbaruch/nanoclaw-admin: tessl__heartbeat` and `jbaruch/nanoclaw-admin: tessl__check-email` — MUST treat any unrecognised shape as "no usable prior state" and let the next owner-skill run rewrite it.

## Files

### `/workspace/group/session-state.json`

Mutable JSON object. Per-group, not shared across containers.

```json
{
  "schema_version": 1,
  "sessions": {
    "<NANOCLAW_SESSION_NAME>": {
      "started":    "<ISO-8601 UTC, e.g. 2026-04-27T15:00:00Z>",
      "epoch":      <int unix seconds>,
      "session_id": "<sqlite session_id from /workspace/store/messages.db, or null>",
      "last_seen":  "<ISO-8601 UTC>"
    }
  },
  "session_id":       "<top-level mirror of the active session_id, back-compat>",
  "pending_response": null,
  "seen_email_ids":   [],
  "muted_threads":    {}
}
```

### Writer / reader contract

| Field | Writers | Readers | Notes |
|---|---|---|---|
| `schema_version` | `register-session.py` (owner) | All readers gate on this | See Schema versioning below |
| `sessions.<name>.*` | `register-session.py` (owner) — own session's subtree | All readers may inspect any session | `last_seen` may be stamped by `tessl__heartbeat` for `maintenance` |
| `session_id` (top-level) | `register-session.py` — both sessions on bootstrap | Legacy readers only | Back-compat; last-writer-wins is accepted |
| `pending_response` | `default` session writes on inbound start; `default` clears on send; `maintenance` heartbeat clears stale entries | All trusted/main sessions | The `pending-response-tracking` rule governs the protocol |
| `seen_email_ids` | `tessl__check-email`, `tessl__heartbeat`, `tessl__morning-brief`, `tessl__nightly` (all `maintenance`) | `tessl__check-email` for de-dup | Append-only within a window |
| `muted_threads` | `default` session | `default` + `maintenance` | Per-thread mute map |

**Back-compat note (legacy migration, ex–`reference_session-state-migration.md`):** the top-level `session_id` field is the pre-`PR jbaruch/nanoclaw#55` shape, when only one session existed per group. It is still written so readers that haven't moved to the per-session subtree continue to work. New readers SHOULD use `sessions.<name>.session_id`. Old single-session files are accepted on read — register-session.py adds the `sessions` subtree without dropping the top-level field, so the migration is in-place and idempotent.

**Other writers on this file** must take `fcntl.LOCK_EX` on `/workspace/group/session-state.json.lock` for the duration of their read-modify-write cycle. Current participants: `jbaruch/nanoclaw-admin: tessl__heartbeat` (writes `last_seen`, clears stale `pending_response`) and `jbaruch/nanoclaw-admin: tessl__check-email` (writes `seen_email_ids`, `pending_response`, `muted_threads`). Without the shared lock, concurrent updates clobber each other.

### `/tmp/session_bootstrapped`

Plain-text sentinel. One line: the value of `$CLAUDE_SESSION_ID` from the run that completed bootstrap.

`needs-bootstrap.py` compares this file's contents to the current `$CLAUDE_SESSION_ID`. Mismatch (or missing file) → bootstrap is needed. `register-session.py` REFUSES to write an empty sentinel because an empty value would match an empty env var on the next run and permanently suppress bootstrap.

## Schema versioning

`session-state.json` carries `schema_version: 1` at the top level. v1 is the current canonical shape: `schema_version` + `sessions.<name>` subtree + back-compat top-level `session_id`. Files written before this field existed are read-tolerated by `register-session.py` (the owner skill) and silently upgraded to v1 on the next write — owner-skill migration per `jbaruch/coding-policy: stateful-artifacts`.

Reader skills (`jbaruch/nanoclaw-admin: tessl__heartbeat`, `jbaruch/nanoclaw-admin: tessl__check-email`) MUST treat an unknown future version (`schema_version > 1`) as "no usable prior state" and let the next `register-session.py` run perform the upgrade — never migrate from a reader.

`/tmp/session_bootstrapped` is a single-line plain-text sentinel; it has no envelope shape to version. The only behavioral contract is "non-empty content = bootstrap was completed for this `$CLAUDE_SESSION_ID`", and that contract is stable.

## `/workspace/trusted/user_profile.md` — `## Addresses` block

`user_profile.md` is a canonical, **special-case** profile file with a fixed filename. It does NOT follow the general `{type}_{slug}.md` typed-memory naming convention in `SKILL.md` (e.g. `user_travel-prefs.md`); the travel-tile reader contract below resolves it by that exact name. It still uses `type: user` frontmatter, and its prose body is agent-read context like any other `user` file. In addition, it carries one **machine-readable** block that scripts parse directly — the canonical `## Addresses` block. Owner skill is `tessl__trusted-memory` (this tile); the block is trusted-tile-owned per `jbaruch/coding-policy: stateful-artifacts`, and every other tile is a **read-only consumer**.

### Shape

```
## Addresses
<!-- canonical, machine-read by travel tile; schema v1 — see trusted-memory state-schema.md -->
- schema_version: 1
- current_home: <current home street address>
- home_airport: <IATA code>
- new_home_wip: <new-build street address>
```

| Key | Meaning | Mutability |
|---|---|---|
| `schema_version` | Block shape version (currently `1`). Bump on any shape change per `jbaruch/coding-policy: stateful-artifacts`. | Owner-only. |
| `current_home` | The operator's current residence — the origin every home-anchored drive leg routes from. | Owner-updated. Switch to the `new_home_wip` value once that home is occupied. |
| `home_airport` | Home IATA code (e.g. `BNA`). | Owner-updated. |
| `new_home_wip` | New-build street address, not yet occupied. | Owner-updated. **Not** auto-promoted to `current_home` — that is an explicit later edit. |

The block **separates** the three address values that the surrounding prose conflates ("home base / new build"). Keep the prose for the agent; the block exists so script reads get an unambiguous single value per key.

### Schema versioning

`schema_version: 1` is the current canonical shape (`current_home` + `home_airport` + `new_home_wip`). Only the owner skill (`tessl__trusted-memory`) bumps it, and only the owner migrates the block — never a reader. Writer and reader ship through separate pipelines (writer here, reader in `jbaruch/nanoclaw-travel`). Coordinate bumps per `jbaruch/coding-policy: stateful-artifacts`:

- **Additive (backward-compatible) bumps** — a new optional key — need no reader change. Bump the version, document the new key here.
- **Breaking bumps** — renaming/removing `current_home` or changing its line shape — deploy the dual-accept reader → change the writer → drop the old shape.

A consumer that does not inspect `schema_version` (the current drive-planner reader does not) treats any version's `- current_home:` line as readable. A future consumer that gates on version MUST treat an unaccepted version as "no usable prior state" and fail closed, never guess an origin.

### Writer / reader contract

| Field | Writer | Readers | Notes |
|---|---|---|---|
| `current_home` | `tessl__trusted-memory` (owner) | `jbaruch/nanoclaw-travel: drive-planner` (read-only) | Origin for home-anchored drive legs. |
| `home_airport` | `tessl__trusted-memory` (owner) | travel-tile consumers (read-only) | IATA code. |
| `new_home_wip` | `tessl__trusted-memory` (owner) | **deliberately ignored** by `drive-planner` | Origin switches are an explicit later change, never an auto-pickup. |

**Travel-tile reader contract (consumer-side).** `jbaruch/nanoclaw-travel`'s `skills/drive-planner/home_address.py` is the read-only consumer of `current_home`. The contract this tile guarantees: a `- current_home: <address>` line under a `## Addresses` heading. The reader **refuses to guess** on a missing or malformed block — it raises an actionable error pointing back at this skill, and drive-planner's sweep fails closed (no blocks created) until the block lands. Parsing details (the match pattern, whitespace tolerance) live in that script and its docstring/tests; owner-side reformatting MUST preserve the `- <key>: <value>` line shape, which a nanoclaw-travel fixture pins.
