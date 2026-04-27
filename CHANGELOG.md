# Changelog

## Unreleased

### Rules

- **no-silent-defer** (new) — Codifies that "deferred" is only legitimate when there's a concrete handoff (resumable-cycle continuation, separately-scheduled task with a different cadence, or an explicit message to the owner). Otherwise the work is skipped, and the skip MUST be surfaced via `mcp__nanoclaw__send_message` rather than buried in a daily summary. Triggered by an incident on 2026-04-27 where `nightly-housekeeping` Step 6 routed 9 unanalyzed CFP candidates to `status: open` + `last_verified: today` with `bot_notes: "AI relevance pass deferred (lean-relevant default)"` — none had been through the AI relevance pass, and the morning-brief `last_verified ≤7 days` safety net was actively defeated by the bogus stamp. Companion compliance updates to `check-cfps` and `nightly-housekeeping` ship in `nanoclaw-admin#63`.

### Test infrastructure

- **pytest baseline + CI gate** (new) — Mirrors the admin-tile scaffold (`nanoclaw-admin#59`): `pyproject.toml` carries `[tool.pytest.ini_options]` and a `tests/`-scoped ruff config; `requirements-dev.txt` pins `pytest==8.3.4` and `ruff==0.7.4`; `.github/workflows/test.yml` runs `ruff check tests/`, `ruff format --check tests/`, then `python -m pytest` on every PR and push to `main`. Initial coverage targets the two new scripts in this PR (`register-session.py`, `needs-bootstrap.py`). Folds the trusted slice of `nanoclaw-admin#55` into this PR per OpenAI policy reviewer requiring tests in the same PR as new modules.

### Scripts

- **register-session.py / needs-bootstrap.py emit JSON status** — Per `jbaruch/coding-policy: script-delegation` (JSON-producing). `register-session.py` prints `{"session_id", "session_name", "schema_version", "wrote_state", "wrote_sentinel"}`; `needs-bootstrap.py` prints `{"needs_bootstrap", "current", "stored", "reason"}`. Exit codes remain the authoritative success signal — JSON is for callers that want to log or inspect. SKILL.md updated to mention both contracts.

### Skills

- **trusted-memory: hook-aware bootstrap note** — Restores the 2-line clarification that the agent-runner's `session-start-auto-context` hook (qwibitai/nanoclaw#141) auto-injects MEMORY.md, RUNBOOK.md, and the most-recent daily log before this skill runs, so the bootstrap's value is the **broader** set the hook does NOT cover (group-shared `trusted/` memory, weekly logs, `highlights.md`) plus the per-session sentinel + state-stamping. The note originated in admin's deleted copy (`nanoclaw-admin@13de2a98`) and was lost when admin's `trusted-memory` was deleted in `nanoclaw-admin#60` (rebase resolved the modify/delete conflict by keeping the deletion). Trusted's canonical copy didn't carry it forward; this restores the context.

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
