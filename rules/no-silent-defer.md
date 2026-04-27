---
alwaysApply: true
---

# No Silent Deferrals

## The Rule

**Defer is allowed only when there is a concrete handoff that will actually do the deferred work.** Otherwise it is a silent skip wearing paperwork — and silent skips on something Baruch intended to act on are material harm, not noise.

## What counts as a concrete handoff

A defer is legitimate ONLY if it points to one of:

1. **A `resumable-cycle` continuation** — capped, container-restarted, with the `HOUSEKEEPING-CAP-HIT` marker explicitly surfaced to the user (skill name, cycle/continuation identifier, where execution stopped).
2. **A separately scheduled task** — actually present in `list_tasks`, with a different cadence/budget than the run that's deferring (otherwise the next run is the same skill under the same constraints and nothing changes).
3. **An explicit message to Baruch** describing what was skipped and asking how to proceed.

If none of those exist, you are not deferring — you are skipping. Mark the work skipped and surface it.

## Forbidden patterns

- "AI relevance pass deferred (lean-relevant default)" while writing `status: open` and `last_verified: today`. The defer-marker contradicts the verified-state stamp; both can't be true.
- "Pragmatic skip — would be N MCP calls in the nightly path" without a concrete continuation pointing where those calls will happen.
- "Relying on next run's [filter / threshold / safety net] to catch this" when next run is the same skill with the same budget.
- Setting `last_verified: <today>` for entries that were not actually verified this run.
- Setting `status: open` for new candidates that did not actually pass the relevance pass they were supposed to.
- `bot_notes` claiming work was deferred when no concrete handoff exists.

## What to do instead

When work cannot be completed in the current run AND no concrete handoff exists:

- **Do not stamp success fields.** No `last_verified: <today>`, no `status: open` for unanalyzed new entries, no `_verified_this_run: true`.
- **Mark the entry incomplete.** Use `_incomplete: true` with a one-line reason in `bot_notes` describing what was not done (e.g. `"Pending: AI relevance pass not run — fetcher truncated at N entries due to budget."`).
- **Surface the skip to the user** in the run's daily summary or via `send_message`. The user must see that something was skipped, in what skill, and why — not discover it weeks later in a state file.

## Why this rule exists

2026-04-27 nightly-housekeeping: Step 6 (check-cfps inside nightly) routed 9 new candidates to `status: open` + `last_verified: today` with `bot_notes: "AI relevance pass deferred (lean-relevant default)"` — none had actually been through the AI relevance pass. The same run "deferred" Sessionize verification of 146 existing `open`/`approved` entries to "a dedicated check-cfps run" that didn't exist. Both were silent skips dressed up as deferrals. The morning-brief `last_verified ≤7 days` gate that was supposed to be the safety net was actively defeated by the bogus stamp.

The principle: a defer that lets a future run catch the work is fine. A defer that points at the same skill with the same budget is a lie — the future run will do the same skip with the same paperwork. If you can't do the work and there's no real handoff, say so. Don't stamp it green.

## Applies to

Every skill that writes state with verification or completion fields — most directly check-cfps, nightly-housekeeping, check-orders, check-email, heartbeat, but the rule is general: any "verified at" / "status: complete" / "last_checked" field is a claim of work done, and is forbidden when the work was not done.
