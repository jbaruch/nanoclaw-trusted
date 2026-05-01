# Changelog

## Unreleased

### Skills — `session-state.json` SQLite migration (tile-side, `jbaruch/nanoclaw#298`)

- **`trusted-memory/scripts/register-session.py` — rewrite to UPSERT `trusted_sessions` + `trusted_session_singleton` rows in SQLite.** The two new tables landed in the orchestrator's state-006 migration. Per-session UPSERT keyed on `session_name` (PK) + per-id UPSERT keyed on `id=1` (singleton CHECK) make sibling-row clobber impossible by construction. The JSON-era `fcntl.LOCK_EX` + tempfile + fsync + chmod-preserve + `os.replace` ceremony retires for both writes; only the `/tmp/session_bootstrapped` sentinel remains file-based (it's a per-container, non-shared bootstrap marker — SQLite isn't the right tool). The singleton UPSERT deliberately omits `pending_response` and `muted_threads` from the UPDATE clause — those columns belong to the default-session writer; pre-existing values survive register-session calls.
- **`trusted-memory/state-schema.md` — rewrite per `coding-policy: stateful-artifacts`.** Two-table contract: `trusted_sessions` (per-session metadata, PK on `session_name`) + `trusted_session_singleton` (CHECK(id=1) singleton with the back-compat `active_session_id` mirror and the JSON-blob payload columns owned by the default-session writer). Writer/reader contracts for the UPSERT + the `last_seen` stamp, concurrency rationale (PK + WAL retire the `session-state.json.lock` sidecar), bootstrap-sentinel carve-out, migration policy.
- **`trusted-memory/SKILL.md` Step 7** — prose now describes the UPSERT into the two SQLite tables instead of the JSON envelope write. The "atomic tempfile+fsync+os.replace" ceremony language retires; the DB-write + sentinel-write transactionality boundary is preserved (DB row updated even if the sentinel write fails — same recovery path as before).
- **`trusted-memory/SKILL.md` Bootstrap Error Handling** — split the JSON-era "missing / corrupt session-state.json" rows into two SQL-era rows: "no `trusted_sessions` row yet" (recoverable, next call establishes) vs "table missing / DB unreachable" (hard failure, points at orchestrator state-006 migration not having run).

The admin-tile's heartbeat-precheck.py last-seen stamp + heartbeat/SKILL.md Hard Rules update for `trusted_sessions` / `trusted_session_singleton` ships in a separate PR (cross-tile work for `#298` requires one PR per repo).

### Tests

- **`tests/test_register_session.py` (rewrite)** — 6 cases pinning the SQLite contract: full roundtrip with both tables UPSERTed, missing $CLAUDE_SESSION_ID skips sentinel, empty `sessions` table records `session_id = NULL`, sibling session rows untouched (the JSON-era cross-session clobber bug retires by construction with PK on session_name), singleton UPSERT preserves `pending_response` / `muted_threads` (default-session writer's columns), DB unreachable → exit 1.

### Skills

- **`system-status` SKILL.md content rewrite — finish #65** (`jbaruch/nanoclaw-admin#65`) — PR #14 (`d35ae5d`) shipped the directory rename, `tile.json` update, the new `scripts/system-status-checks.py`, and the test suite, but the new `skills/system-status/SKILL.md` was created with the **legacy content** verbatim — same `name: check-system-health` frontmatter, same three `python3 -c "..."` inline blocks the rewrite was supposed to remove. The CHANGELOG entry below describes the rewrite that PR #14 intended; this PR actually performs it: frontmatter `name` → `system-status`, body collapsed to Step 1 (run `system-status-checks.py`) / Step 2 (act on `alerts`), description tightened to read-only-trusted-tier scope, dismiss-mechanism section dropped (admin's domain), explicit "What this skill is NOT" section added. `tessl skill review skills/system-status` reports 100%.

- **`check-system-health` renamed to `system-status` + content rewritten** — Resolves the cross-tile name collision flagged in `nanoclaw-admin#52` / `#65` (admin and trusted both shipped a skill named `check-system-health`, both installing under `tessl__check-system-health/` so the second-installed copy shadowed the first silently). Per the owner-recorded split decision: admin keeps the full SQLite + filesystem + IPC + container probe with the dismiss-mechanism management; trusted gets a read-only narrower subset under the new non-colliding name. The three previous `python3 -c "..."` inline blocks (which violated `coding-policy: script-delegation`) move to `scripts/system-status-checks.py` as a single deterministic JSON-producing probe; SKILL.md becomes prose-and-action with explicit Step 1 (run script) / Step 2 (act on alerts). The dismiss-mechanism section is dropped — trusted is read-only with respect to admin's dismiss state. `tile.json` rule entry renamed `check-system-health` → `system-status`. `tests/test_system_status_checks.py` covers seven scenarios: missing DB → exit 1, clean DB → empty alerts, stuck-task threshold crossing, recent failure within 24h, old failure outside 24h excluded, message rowcount above threshold, DB size above threshold.

### Rules

- **installed-content-immutable** (new) — Codifies the kernel-level read-only contract on `/home/node/.claude/skills/` and `/home/node/.claude/.tessl/` introduced in `jbaruch/nanoclaw#247`. Two read-only bind-mounts layer on top of the writable `/home/node/.claude` parent so `Write`/`Edit` against installed content returns `EROFS` rather than silently mutating an in-memory copy that gets rebuilt at the next container spawn. Documents what's still writable (transcripts, debug, todos, telemetry, session-env, auto-memory overlay), and the canonical staging → promote (`tessl__promote-tiles`) → publish (`publish-tile.yml`) → update (`./scripts/deploy.sh`) → spawn pipeline operators must use to actually change a skill or rule.
- **no-silent-defer** (new) — Codifies that "deferred" is only legitimate when there's a concrete handoff (resumable-cycle continuation, separately-scheduled task with a different cadence, or an explicit message to the owner). Otherwise the work is skipped, and the skip MUST be surfaced via `mcp__nanoclaw__send_message` rather than buried in a daily summary. Triggered by an incident on 2026-04-27 where `nightly-housekeeping` Step 6 routed 9 unanalyzed CFP candidates to `status: open` + `last_verified: today` with `bot_notes: "AI relevance pass deferred (lean-relevant default)"` — none had been through the AI relevance pass, and the morning-brief `last_verified ≤7 days` safety net was actively defeated by the bogus stamp. Companion compliance updates to `check-cfps` and `nightly-housekeeping` ship in `nanoclaw-admin#63`.

### Test infrastructure

- **pytest baseline + CI gate** (new) — Mirrors the admin-tile scaffold (`nanoclaw-admin#59`): `pyproject.toml` carries `[tool.pytest.ini_options]` and a `tests/`-scoped ruff config; `requirements-dev.txt` pins `pytest==8.3.4` and `ruff==0.7.4`; `.github/workflows/test.yml` runs `ruff check tests/`, `ruff format --check tests/`, then `python -m pytest` on every PR and push to `main`. Initial coverage targets the two new scripts in this PR (`register-session.py`, `needs-bootstrap.py`). Folds the trusted slice of `nanoclaw-admin#55` into this PR per OpenAI policy reviewer requiring tests in the same PR as new modules.

### Scripts

- **register-session.py / needs-bootstrap.py emit JSON status** — Per `jbaruch/coding-policy: script-delegation` (JSON-producing). `register-session.py` prints `{"session_id", "session_name", "schema_version", "wrote_state", "wrote_sentinel"}`; `needs-bootstrap.py` prints `{"needs_bootstrap", "current", "stored", "reason"}`. Exit codes remain the authoritative success signal — JSON is for callers that want to log or inspect. SKILL.md updated to mention both contracts.

### Skills

- **trusted-memory: hook-aware bootstrap note** — Restores the 2-line clarification that the agent-runner's `session-start-auto-context` hook (jbaruch/nanoclaw#141) auto-injects MEMORY.md, RUNBOOK.md, and the most-recent daily log before this skill runs, so the bootstrap's value is the **broader** set the hook does NOT cover (group-shared `trusted/` memory, weekly logs, `highlights.md`) plus the per-session sentinel + state-stamping. The note originated in admin's deleted copy (`nanoclaw-admin@13de2a98`) and was lost when admin's `trusted-memory` was deleted in `nanoclaw-admin#60` (rebase resolved the modify/delete conflict by keeping the deletion). Trusted's canonical copy didn't carry it forward; this restores the context.

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
