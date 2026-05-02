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

Prose enforcement of "remember to surface" is itself prose under context pressure — the same shape that drove `jbaruch/nanoclaw#265` (CFP `tier3_skipped: nightly budget`) and the multi-cycle path-hygiene re-reports. Move the surfacing decision from "the LLM remembers" to "the caller checks file existence."

When a sub-skill defers or skips work, it MUST emit a structured skip-summary file at the well-known path `/workspace/group/.skip-summary-<tessl-skill-id>.json`, where `<tessl-skill-id>` is the full `tessl__<name>` identifier (e.g. `.skip-summary-tessl__check-cfps.json`). One file per skill — concurrent skips from different skills don't collide.

### Required fields

- `schema_version` — integer, currently `1`. Bump when the on-disk shape changes per `jbaruch/coding-policy: stateful-artifacts`.
- `skill` — string, the same `tessl__<name>` identifier used in the filename suffix. Surfacing routes can label or filter on this field without re-parsing the path.
- `step` — string or integer. Which step within the skill triggered the skip (helps the owner reproduce or override).
- `reason` — string, one-line summary suitable for a Telegram message body. No multi-paragraph prose.
- `items` — array of strings. Stable identifiers for the skipped entries (CFP IDs, email IDs, order rows, …) so the owner can act on them individually. Empty array when the skip is global, e.g. "nightly budget exhausted, no per-item context."
- `technical_failure` — boolean. `true` for transient failures (API timeout, lock contention, network) where a retry would likely succeed; `false` for policy skips (budget exhausted, deferred-by-design). The surfacer surfaces both, but the owner can route them differently — technical → silent retry on next cycle; policy → ask owner what to do.
- `occurred_at` — string, UTC ISO-8601 with `Z` suffix. Lets the owner correlate the skip with a chat-side event when the surfacing message arrives moments later.

### Lifecycle and actor responsibilities

The contract has two actors — the **owner skill** that performed the skip and the **surfacer** that reads and reports it. The surfacer is whichever skill (or orchestrator after-skill hook) called the owner skill via `Skill(...)`; it varies by call chain.

- **Owner skill**: writes the file once, atomically (`tempfile + fsync + os.replace`), then returns. Does NOT read or delete its own file — the surfacer owns the read-surface-delete sequence so the file's existence is the deterministic signal across the call boundary.
- **Surfacer**: after the owner skill returns, reads the file, calls `mcp__nanoclaw__send_message` with the rendered content, then deletes the file. The delete is the surfacer's responsibility because it knows the surfacing actually completed; if the owner skill deleted on its way out, a surfacer that hasn't run yet would lose the signal.
- **Owner-skill state-shape ownership**: per `jbaruch/coding-policy: stateful-artifacts`, only the owner skill migrates the schema. Surfacers (and any other readers) treat an unrecognised `schema_version` as "no usable prior state" and skip the surfacing rather than guessing.
- **Cardinality**: a skill MAY emit zero or one skip-summary per run; never multiple. If multiple steps within the same skill skip independently, aggregate them into one summary's `items` list.

### Linting (planned)

A pre-publish lint scan on each tile verifies (a) every `## Forbidden patterns` example in this rule has a corresponding negative-case test in the implementing skill, and (b) skills that emit `.skip-summary-<tessl-skill-id>.json` follow the lifecycle above (owner writes, surfacer deletes — no stale-file leaks). Tracked under `jbaruch/nanoclaw#277` part B.

## Applies to

Every skill that writes state with verification or completion fields — directly `check-cfps`, `nightly-housekeeping`, `check-orders`, `check-email`, `heartbeat`, but the rule is general: any "verified at" / "status: complete" / "last_checked" field is a claim of work done, forbidden when the work wasn't.
