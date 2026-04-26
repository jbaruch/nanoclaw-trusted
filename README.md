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
| [daily-discoveries-rule](rules/daily-discoveries-rule.md) | When you learn something new and operationally important — a workflow, where something lives, how something works, a tool to use for a specific task — immediately write it to… |
| [ground-truth-trusted](rules/ground-truth-trusted.md) | Extends the core ground-truth rule with verification methods and computation available to trusted containers via Composio. |
| [memory-file-locations](rules/memory-file-locations.md) | 1. **All typed memory files go in `/workspace/trusted/` root** — never in `/workspace/trusted/memory/`. The `memory/` subdirectory is ONLY for daily logs and daily_discoveries. |
| [no-orphan-tasks](rules/no-orphan-tasks.md) | **Never create a standalone scheduled task for something that can go into an existing scheduled workflow.** |
| [proactive-fact-saving](rules/proactive-fact-saving.md) | Personal facts mentioned in conversation must be saved to trusted memory IMMEDIATELY — not at end of session, not during archival, not "when non-trivial." At first mention. |
| [session-bootstrap](rules/session-bootstrap.md) | **YOUR VERY FIRST ACTION in every new session — before responding to ANY message — is to run this Bash command:** |
| [skill-dependencies](rules/skill-dependencies.md) | Skills that invoke or depend on other skills. Read this to understand execution order and shared state. |
| [trusted-behavior](rules/trusted-behavior.md) | Extends core-behavior with additional rules for trusted and main containers. Everything in core still applies — this adds to it. |
| [verification-protocol](rules/verification-protocol.md) | After these actions, verify independently before confirming to the user: |
| [wiki-awareness](rules/wiki-awareness.md) | A persistent personal wiki lives at `/workspace/trusted/wiki/` with raw sources at `/workspace/trusted/sources/`. |

## Skills

| Skill | Description |
|-------|-------------|
| [check-system-health](skills/check-system-health/SKILL.md) | name: check-system-health |
| [trusted-memory](skills/trusted-memory/SKILL.md) | name: trusted-memory |

See [CHANGELOG.md](CHANGELOG.md) for version history.
