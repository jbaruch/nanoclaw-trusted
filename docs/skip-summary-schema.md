# Skip-Summary File Schema

Reference for the structured skip-summary file contract enforced by `rules/no-silent-defer.md`. Skill authors and pre-publish lint scripts read this; the file is not auto-loaded into agent context.

## Why a file, not prose

Prose enforcement of "remember to surface" is itself prose under context pressure — the same shape that drove `jbaruch/nanoclaw#265` (CFP `tier3_skipped: nightly budget`) and the multi-cycle path-hygiene re-reports. Move the surfacing decision from "the LLM remembers" to "the caller checks file existence."

## File location

When a sub-skill defers or skips work, it MUST emit a structured skip-summary file at the well-known path `/workspace/group/.skip-summary-<tessl-skill-id>.json`, where `<tessl-skill-id>` is the full `tessl__<name>` identifier (e.g. `.skip-summary-tessl__check-cfps.json`). One file per skill — concurrent skips from different skills don't collide.

## Required fields

- `schema_version` — integer, currently `1`. Bump when the on-disk shape changes per `jbaruch/coding-policy: stateful-artifacts`.
- `skill` — string, the same `tessl__<name>` identifier used in the filename suffix. Surfacing routes can label or filter on this field without re-parsing the path.
- `step` — string or integer. Which step within the skill triggered the skip (helps the owner reproduce or override).
- `reason` — string, one-line summary suitable for a Telegram message body. No multi-paragraph prose.
- `items` — array of strings. Stable identifiers for the skipped entries (CFP IDs, email IDs, order rows, …) so the owner can act on them individually. Empty array when the skip is global, e.g. "nightly budget exhausted, no per-item context."
- `technical_failure` — boolean. `true` for transient failures (API timeout, lock contention, network) where a retry would likely succeed; `false` for policy skips (budget exhausted, deferred-by-design). The surfacer surfaces both, but the owner can route them differently — technical → silent retry on next cycle; policy → ask owner what to do.
- `occurred_at` — string, UTC ISO-8601 with `Z` suffix. Lets the owner correlate the skip with a chat-side event when the surfacing message arrives moments later.

## Lifecycle and actor responsibilities

The contract has two actors — the **owner skill** that performed the skip and the **surfacer** that reads and reports it. The surfacer is whichever skill (or orchestrator after-skill hook) called the owner skill via `Skill(...)`; it varies by call chain.

- **Owner skill**: writes the file once, atomically (`tempfile + fsync + os.replace`), then returns. Does NOT read or delete its own file — the surfacer owns the read-surface-delete sequence so the file's existence is the deterministic signal across the call boundary.
- **Surfacer**: after the owner skill returns, reads the file, calls `mcp__nanoclaw__send_message` with the rendered content, then deletes the file. The delete is the surfacer's responsibility because it knows the surfacing actually completed; if the owner skill deleted on its way out, a surfacer that hasn't run yet would lose the signal.
- **Owner-skill state-shape ownership**: per `jbaruch/coding-policy: stateful-artifacts`, only the owner skill migrates the schema. Surfacers (and any other readers) treat an unrecognised `schema_version` as "no usable prior state" and skip the surfacing rather than guessing.
- **Cardinality**: a skill MAY emit zero or one skip-summary per run; never multiple. If multiple steps within the same skill skip independently, aggregate them into one summary's `items` list.

## Linting (planned)

A pre-publish lint scan on each tile verifies (a) every `## Forbidden patterns` example in `rules/no-silent-defer.md` has a corresponding negative-case test in the implementing skill, and (b) skills that emit `.skip-summary-<tessl-skill-id>.json` follow the lifecycle above (owner writes, surfacer deletes — no stale-file leaks). Tracked under `jbaruch/nanoclaw#277` part B.
