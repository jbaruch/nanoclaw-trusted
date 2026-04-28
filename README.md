# jbaruch/nanoclaw-trusted

[![tessl](https://img.shields.io/endpoint?url=https%3A%2F%2Fapi.tessl.io%2Fv1%2Fbadges%2Fjbaruch%2Fnanoclaw-trusted)](https://tessl.io/registry/jbaruch/nanoclaw-trusted)

Rules for trusted NanoClaw groups. Shared memory, session bootstrap, cross-group memory updates. Loaded for trusted and admin scope.

## Installation

```
tessl install jbaruch/nanoclaw-trusted
```

## Rules

| Rule | Summary |
|------|---------|
| [compaction-aware-summaries](rules/compaction-aware-summaries.md) | When Claude Code compacts context, the summary must preserve information that cannot be recovered from files alone. |
| [daily-discoveries-rule](rules/daily-discoveries-rule.md) | When you learn something new and operationally important — a workflow, where something lives, how something works, a tool to use for a specific task — immediately write it to `/workspace/trusted/memory/daily_discoveries.md`: |
| [ground-truth-trusted](rules/ground-truth-trusted.md) | Extends the core ground-truth rule with verification methods and computation available to trusted containers via Composio. |
| [memory-file-locations](rules/memory-file-locations.md) | 1. **All typed memory files go in `/workspace/trusted/` root** — never in `/workspace/trusted/memory/`. The `memory/` subdirectory is ONLY for daily logs and daily_discoveries. |
| [no-orphan-tasks](rules/no-orphan-tasks.md) | Before scheduling any new recurring task, check: |
| [no-silent-defer](rules/no-silent-defer.md) | Defer is allowed only when there is a concrete handoff that will actually do the deferred work. Otherwise it is a silent skip — and silent skips on something the owner intended to act on are material harm, not noise. |
| [proactive-fact-saving](rules/proactive-fact-saving.md) | Personal facts mentioned in conversation must be saved to trusted memory IMMEDIATELY — not at end of session, not during archival, not "when non-trivial." At first mention. |
| [session-bootstrap](rules/session-bootstrap.md) | Then write the sentinel: `echo "done" > /tmp/session_bootstrapped` |
| [skill-dependencies](rules/skill-dependencies.md) | Skills that invoke or depend on other skills. Read this to understand execution order and shared state. |
| [trusted-behavior](rules/trusted-behavior.md) | Extends core-behavior with additional rules for trusted and main containers. Everything in core still applies — this adds to it. |
| [verification-protocol](rules/verification-protocol.md) | After these actions, verify independently before confirming to the user: |
| [wiki-awareness](rules/wiki-awareness.md) | A persistent personal wiki lives at `/workspace/trusted/wiki/` with raw sources at `/workspace/trusted/sources/`. |

## Skills

| Skill | Description |
|-------|-------------|
| [system-status](skills/system-status/SKILL.md) | Read-only system-status probe for trusted-tier NanoClaw containers — surfaces stuck scheduled tasks, DB size, and recent task-run failures from the orchestrator's SQLite. Use as part of heartbeat or standalone. Renamed from `check-system-health` (which collided with the admin tile's same-named skill, per `nanoclaw-admin#65`); admin keeps the canonical full health probe with dismiss-mechanism management. |
| [trusted-memory](skills/trusted-memory/SKILL.md) | Session bootstrap and rolling memory updates for trusted containers. On session start, reads MEMORY.md (permanent facts), RUNBOOK.md (operational workflows), recent daily and weekly logs, and highlights.md to restore context. After non-trivial interactions, appends timestamped entries to group-local and cross-group shared daily logs. Use when starting a new session to load previous notes and remember context, or after meaningful conversations to save conversation history, persist session state, or record newly learned owner preferences. |

See [CHANGELOG.md](CHANGELOG.md) for version history.
