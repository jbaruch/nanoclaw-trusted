# Changelog

## Unreleased

### Scripts

- **`trusted-memory/scripts/append-to-daily-log.py` (new)** — Replaces the LLM-driven `read → modify → Write` flow for daily-log appends with a deterministic helper that holds `fcntl.LOCK_EX` on `<daily-file>.lock` for the read-modify-write cycle. The previous prose contract (`SKILL.md` "Rolling Memory Updates") was racy under concurrent appends from default + maintenance containers + sub-skills: container A's read + container B's write between A's read and write meant A's append silently overwrote B's. Helper auto-creates the daily file with `# Daily Summary — YYYY-MM-DD` header on first write (matches `archive-helper.py`'s daily-header regex), warns on non-monotonic `HH:MM UTC` prefix without dropping the entry, and emits `{"path", "appended_lines", "final_line_count", "monotonic"}` on stdout per `jbaruch/coding-policy: script-delegation`. Tests cover header creation, prior-line preservation (the breaking shape from `jbaruch/nanoclaw#266`), batch appends via `--lines-file`, non-monotonic warning, target routing, concurrent-writer serialisation, CLI errors, and atomic-write mode preservation. Closes `jbaruch/nanoclaw#275`.
- **`trusted-memory` SKILL.md** — "Rolling Memory Updates" section rewritten to invoke `scripts/append-to-daily-log.py` for both group-local and cross-group appends, replacing the prior prose append-via-`Write` contract.

### Skills

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
