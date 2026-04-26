---
alwaysApply: true
---

# No Orphan Scheduled Tasks

## The Rule

**Never create a standalone scheduled task for something that can go into an existing scheduled workflow.**

Before scheduling any new recurring task, check:

1. Does nightly-housekeeping already run nightly? → add it there as a new step
2. Does heartbeat already run every 15 min? → add it there if it needs frequent checks
3. Does morning-brief already run daily? → add it there if it's morning-relevant

## What belongs in nightly-housekeeping

Any daily recurring check that:
- Doesn't need to run more than once a day
- Produces results Baruch can see in the morning
- Involves fetching data, checking state, or generating a report

Examples: YouTube comment checks, GitHub activity summaries, CFP state refresh, email triage.

## When a standalone task IS appropriate

- One-off reminders (calendar events, deadlines) — these are inherently standalone
- Checks that need a specific frequency different from existing workflows (e.g., every 4 hours)
- Tasks for other groups (target_group_jid)

## How to add to nightly-housekeeping

Edit the nightly-housekeeping SKILL.md to add a new numbered step. Do not create a cron task.

File: `/home/node/.claude/skills/tessl__nightly-housekeeping/SKILL.md`

Stage the change and promote via `tessl__promote-tiles`.
