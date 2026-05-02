---
alwaysApply: true
---

# No Silent Deferrals

## The rule

**Defer is allowed only when there is a concrete handoff that will actually do the deferred work.** Otherwise it is a silent skip wearing paperwork — and silent skips on something the owner intended to act on are material harm, not noise.

## What counts as a concrete handoff

A defer is legitimate ONLY if it points to one of:

1. **A `resumable-cycle` continuation** — capped, container-restarted, with the `HOUSEKEEPING-CAP-HIT` marker explicitly surfaced to the user (skill name, cycle/continuation id, where execution stopped).
2. **A separately scheduled task** — actually present in `list_tasks`, with a different cadence/budget than the run that's deferring (otherwise next run is the same skill under the same constraints — nothing changes).
3. **An explicit message to the owner** describing what was skipped and asking how to proceed.

If none exist, you are not deferring — you are skipping. Mark the work skipped and surface it.

## Forbidden patterns

- "Deferred (lean-relevant default)" while writing `status: open` + `last_verified: today` — defer-marker and verified-state stamp can't both be true.
- "Pragmatic skip — N MCP calls in the nightly path" with no concrete continuation pointing where those calls will happen.
- "Next run's [filter / threshold / safety net] will catch this" when next run is the same skill with the same budget.
- Setting `last_verified: <today>` for entries not actually verified this run.
- Setting `status: open` for new candidates that did not pass the relevance pass.
- `bot_notes` claiming work was deferred when no concrete handoff exists.

## What to do instead

- **Do not stamp success fields.** No `last_verified: <today>`, no `status: open` for unanalyzed entries, no `_verified_this_run: true`.
- **Use the skill's documented incomplete-pass mechanism** (see each skill's "Incomplete-pass contract" — e.g. `check-cfps`'s `cfp-pending.json` + `_verify_skipped: true`, with a structured report to the caller).
- **Surface the skip to the owner** via `mcp__nanoclaw__send_message` in the same run. Discovering a skip weeks later in a state file is the failure mode this rule prevents.

## Skip-summary file contract (deterministic surfacing)

A skill that defers or skips work writes a structured summary file at `/workspace/group/.skip-summary-<tessl-skill-id>.json`. The surfacer reads, sends via `mcp__nanoclaw__send_message`, and deletes. Owner skill writes; surfacer reads-sends-deletes — the file's existence is the deterministic signal across the call boundary, so prose enforcement of "remember to surface" can't slip under context pressure. Schema, field-by-field reference, full lifecycle, and the planned pre-publish lint: see `docs/skip-summary-schema.md`.

## Applies to

Every skill that writes state with verification or completion fields — directly `check-cfps`, `nightly-housekeeping`, `check-orders`, `check-email`, `heartbeat`, but the rule is general: any "verified at" / "status: complete" / "last_checked" field is a claim of work done, forbidden when the work wasn't.
