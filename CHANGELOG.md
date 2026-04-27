# Changelog

## Unreleased

### Skills

- **trusted-memory absorbs admin's improvements** — The admin tile carried a parallel `trusted-memory` copy that diverged after `nanoclaw-admin#31` extracted inline Python into helper scripts. Per audit decision (closes `nanoclaw-admin#52`), trusted is the canonical home for this skill. This change pulls admin's structural improvements into trusted's copy:
  - `scripts/needs-bootstrap.py` (new) — sentinel-vs-`$CLAUDE_SESSION_ID` check, replacing the inline 8-line block; exit 0 = bootstrap needed, exit 1 = skip.
  - `scripts/register-session.py` (new) — atomic `session-state.json` + `/tmp/session_bootstrapped` write under `fcntl.LOCK_EX`. Reads session_id from `/workspace/store/messages.db` with a 10s timeout; tolerates `sqlite3.Error` as `session_id=None` rather than crashing the whole bootstrap; refuses to write an empty sentinel (would silently disable bootstrap forever).
  - `scripts/sync-session-id.py` (deleted) — superseded by `register-session.py`. The new script subsumes its session-id mirroring AND adds the sentinel write that previously lived inline as Step 8.
  - `state-schema.md` (new) — documents `session-state.json` shape (`sessions.<name>` subtree + top-level `session_id` back-compat from `jbaruch/nanoclaw#55`) and the `/tmp/session_bootstrapped` sentinel contract per `jbaruch/coding-policy: stateful-artifacts`. Replaces the dangling `reference_session-state-migration.md` link in admin's SKILL.md (file was referenced but never written).
  - `SKILL.md` updated to admin's structure with two adjustments: dangling `reference_memory-types.md` link replaced by inlining the per-type frontmatter examples (the link target was likewise never written), and the `reference_session-state-migration.md` link redirected to the new `state-schema.md`.

  Removal from admin's tile lands in `nanoclaw-admin` separately. Refs `nanoclaw-admin#52`.

### Surface sync

- `tile.json` adds `entrypoint: README.md` per `jbaruch/coding-policy: context-artifacts`.
- `README.md` and `CHANGELOG.md` introduced (none existed previously). Both will be maintained going forward as required by the policy.

The README's rules-table summaries are auto-extracted first-paragraph excerpts from each rule file. Refine them per rule when the wording is misleading; this commit is a structural bootstrap, not authored prose.
