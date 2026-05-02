# Skill Execution Order and Shared State

Reference for skill authors working on the cron-driven trusted-tier flows. Captures which skills invoke which others, in what order, and which state files form the read/write contract between them. Read this on demand when modifying a skill that participates in one of these chains; it is not always-loaded into the agent prefix.

The contents below were the always-loaded `rules/skill-dependencies.md` rule before `jbaruch/nanoclaw-admin#180` (RULES.md diet) moved them here per the umbrella's "developer reference out of always-loaded rules" trim approach.

> **Currency note:** the per-step descriptions reflect the pre-`jbaruch/nanoclaw#404` housekeeping split (`nightly-housekeeping` / `morning-brief` as monoliths). The split shipped 11 independent sub-skills (admin PRs `#159`, `#161`, `#163`, `#165`–`#172`); the monoliths are now run-accounting shells. The shared-state table below remains the authoritative reader/writer contract; the step-numbered narratives are a snapshot, not the current truth — update the relevant section in a follow-up PR if you re-derive the post-split chain.

## Heartbeat (runs every 15 min)
1. Calls `task-tz-sync` (Step 0.5) — detects timezone changes
2. Checks `task-tz-state.json` for missed tasks (Step 0.6) — may invoke `morning-brief` or `nightly-housekeeping`
3. Runs `heartbeat-checks.py` script (Step 1) — system health checks directly via script

## Morning Brief (runs daily, 8am local)
1. Reads Google Calendar via Composio (Step 1)
2. Reads Google Tasks via Composio (Step 2)
3. Runs `morning-brief-fetch.py` script (Step 3) — reads `morning-brief-pending.json`
4. Runs `morning-brief-cfp.py` script (Step 4a) — reads CFP state
5. Calls `check-calendar` internally (Step 8) — sets up reminders
6. Updates `task-tz-state.json` with `last_run_date` (Step 9)

## Nightly Housekeeping (runs daily, 11pm local)
1. Calls `check-travel-bookings` (Step 4)
2. Calls `check-orders` (Step 6)
3. Writes `morning-brief-pending.json` (Step 9) — consumed by next morning-brief
4. Deduplicates daily logs via Jaccard similarity (Step 11)
5. Archives daily logs → weekly with importance classification (Steps 12-14)
6. Calls `check-watchlist` (Step 16)
7. Updates `task-tz-state.json` with `last_run_date` (Step 17)
8. Runs backup script + `github_backup` MCP (Step 18)

## Shared State Files
| File | Written by | Read by |
|------|-----------|---------|
| `task-tz-state.json` | task-tz-sync, morning-brief, nightly-housekeeping | heartbeat (missed task detection) |
| `morning-brief-pending.json` | nightly-housekeeping (Step 6) | morning-brief (Step 3) |
| `session-state.json` | any skill (pending response tracking) | heartbeat (pending response check) |
| `calendar-state.json` | check-calendar | check-calendar (diff against previous) |
| `cfp-state.json` | check-cfps | check-cfps, morning-brief-cfp.py |
