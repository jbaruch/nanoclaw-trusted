---
alwaysApply: true
---

# No Orphan Scheduled Tasks

**Never create a standalone scheduled task for something that fits an existing scheduled workflow.** Before scheduling a new recurring task, check whether the cadence matches one of the existing flows: nightly-housekeeping (daily, owner sees results in the morning brief), heartbeat (every 15 min), or morning-brief (daily, morning-relevant). If yes, add it there instead — staged + promoted via `tessl__promote-tiles`, not as a fresh cron row.

## When a standalone task IS appropriate

- One-off reminders (calendar events, deadlines) — inherently standalone.
- Checks needing a frequency that doesn't match any existing flow (e.g. every 4 hours).
- Tasks targeting another group (`target_group_jid`).

## What belongs in nightly-housekeeping

Daily checks that produce a report the owner reads in the morning brief — fetches, state refreshes, summary generation. Examples: YouTube comment checks, GitHub activity summaries, CFP state refresh, email triage. The pre-`#404` pattern was a numbered step in the monolith SKILL.md; post-split (`jbaruch/nanoclaw#404`), the canonical pattern is an independent sub-skill row scheduled at the same cadence.
