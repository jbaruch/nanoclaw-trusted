---
alwaysApply: true
---

# No Silent Deferrals

## Concrete handoff

- Defer only with one of these handoffs:
  1. A capped, container-restarted `resumable-cycle` continuation; surface `HOUSEKEEPING-CAP-HIT`, skill name, cycle/continuation ID, and stopping point.
  2. A separate task present in `list_tasks`, with a different cadence/budget from this run.
  3. An explicit message to the owner describing skipped work and asking how to proceed.
- Without a handoff, mark work skipped and surface it.

## Forbidden patterns

- Apply to every skill writing verification or completion state.
- Never stamp unverified work with `last_verified`, `last_checked`, `_verified_this_run: true`, or completion fields.
- Never set `status: open` for new candidates that have not passed relevance analysis.
- Never combine a defer marker with a verified-state stamp.
- Never claim deferral in `bot_notes` without a concrete handoff.
- A call budget or the next run's unchanged filter, threshold, or safety net is not a handoff.

## Incomplete work

- Use the skill's incomplete-pass mechanism, such as `*-pending.json` with `_verify_skipped: true` and a structured report to the caller.
- Surface skips to the owner via `mcp__nanoclaw__send_message` in the same run.

## Skip-summary file

- A deferring or skipping skill writes `/workspace/group/.skip-summary-<tessl-skill-id>.json`.
- Use the full `tessl__<name>` identifier; keep one file per skill.
- Owner skill writes; surfacer reads, sends via `mcp__nanoclaw__send_message`, and deletes.
- Schema, fields, lifecycle, and pre-publish lint: `skills/trusted-memory/references/skip-summary-schema.md`.
