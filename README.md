# jbaruch/nanoclaw-trusted

[![tessl](https://img.shields.io/endpoint?url=https%3A%2F%2Fapi.tessl.io%2Fv1%2Fbadges%2Fjbaruch%2Fnanoclaw-trusted)](https://tessl.io/registry/jbaruch/nanoclaw-trusted)

Rules for trusted NanoClaw groups. Shared memory, session bootstrap, cross-group memory updates. Loaded for trusted and admin scope.

## Installation

```
tessl install jbaruch/nanoclaw-trusted
```

## Rules

Always-on rules are loaded into every turn's context. Conditional rules are loaded by the agent's model when their `applyTo:` clause matches the current task — kept off baseline context otherwise per `jbaruch/coding-policy: rule-frontmatter`.

| Rule | Scope | Summary |
|------|-------|---------|
| [compaction-aware-summaries](rules/compaction-aware-summaries.md) | conditional | When Claude Code compacts context, the summary must preserve information that cannot be recovered from files alone. |
| [daily-discoveries-rule](rules/daily-discoveries-rule.md) | conditional | When you learn something new and operationally important — a workflow, where something lives, how something works, a tool to use for a specific task — immediately write it to `/workspace/trusted/memory/daily_discoveries.md`: |
| [github-data-via-gh](rules/github-data-via-gh.md) | conditional | GitHub state — PRs, issues, repo contents, workflow runs — comes from the `gh` CLI inside the container (orchestrator forwards `GITHUB_TOKEN` per `jbaruch/nanoclaw#565`). `curl https://api.github.com/...` is still wrong (unauthenticated); `gh` is the only path, with no fallback. |
| [identity-dual-handle](rules/identity-dual-handle.md) | always-on | Deploy-tier extension of the dual-handle invariant in `jbaruch/nanoclaw-core` `rules/core-behavior.md`. |
| [installed-content-immutable](rules/installed-content-immutable.md) | conditional | Installed skills and rules under `/home/node/.claude/skills/` and `/home/node/.claude/.tessl/` are kernel-level read-only at runtime — `Write`/`Edit` against them returns `EROFS`. Real changes flow through the staging → promote → publish → update pipeline. |
| [local-context-anchoring](rules/local-context-anchoring.md) | always-on | Anchor every relative time/place phrasing (`today` / `yesterday` / `now` / `here`, plus Russian equivalents) to the user's local frame from the orchestrator-injected `<context>` tag's `local_datetime` / `weekday` / `location_*` attrs — not the server clock and not UTC. |
| [memory-file-locations](rules/memory-file-locations.md) | conditional | 1. **All typed memory files go in `/workspace/trusted/` root** — never in `/workspace/trusted/memory/`. The `memory/` subdirectory is ONLY for daily logs and daily_discoveries. |
| [messages-db-schema](rules/messages-db-schema.md) | conditional | Requires the [schema reference](skills/system-status/references/messages-db-schema.md) before DB queries or column references. |
| [no-orphan-tasks](rules/no-orphan-tasks.md) | conditional | Before scheduling any new recurring task, check: |
| [no-silent-defer](rules/no-silent-defer.md) | always-on | Requires a concrete handoff, truthful verification state, and a surfaced skip summary for incomplete work. |
| [proactive-fact-saving](rules/proactive-fact-saving.md) | always-on | Personal facts mentioned in conversation must be saved to trusted memory IMMEDIATELY — not at end of session, not during archival, not "when non-trivial." At first mention. |
| [session-bootstrap](rules/session-bootstrap.md) | conditional | At session start, invoke the `tessl__trusted-memory` skill to load memory; the skill self-gates via its per-session `$CLAUDE_SESSION_ID` sentinel. |
| [async-tasks-extended](rules/async-tasks-extended.md) | always-on | Trusted-tier extension of the core async-tasks protocol — reaction upgrade, background-agent spawn, scheduled-task silence, post-compaction restart. |
| [container-trust-levels](rules/container-trust-levels.md) | always-on | Runtime detection is the contract: read-only-filesystem error = untrusted container, don't retry. Full capability matrix in `docs/trust-tier-capabilities.md`. |
| [context-bootstrap-bg-agents](rules/context-bootstrap-bg-agents.md) | conditional | Background-agent prompts must include workspace context (paths, send-message tool, Telegram HTML formatting). |
| [duplicate-prevention](rules/duplicate-prevention.md) | always-on | Before creating any resource, check if it exists. Duplicate found → update existing. |
| [global-memory](rules/global-memory.md) | always-on | `/workspace/global/CLAUDE.md` for cross-group facts. Only update when explicitly asked. |
| [humanize-outbound-prose](rules/humanize-outbound-prose.md) | conditional | Run `tessl__blog-writer`'s humanization pass on every email draft, or other prose sent under the operator's name, before posting it; talk abstracts, other speakers' too, go through `tessl__cfp-abstract` first as one text. |
| [identity-compaction-recovery](rules/identity-compaction-recovery.md) | conditional | After context compaction, re-read `/workspace/global/SOUL.md` — your persona context is gone. |
| [pending-response-tracking](rules/pending-response-tracking.md) | always-on | Stamp `session-state.json` with `pending_response`, do the work, send, clear. Heartbeat picks up interrupted responses. |
| [proactive-participation](rules/proactive-participation.md) | always-on | In trusted groups you're a participant — chime in when useful. Default-silence still applies; a reaction alone is complete participation. |
| [reply-threading](rules/reply-threading.md) | always-on | Always reply-thread user messages using `reply_to`. Required for heartbeat to track unanswered messages. |
| [skills-policy](rules/skills-policy.md) | always-on | If a skill exists, invoke it with `Skill(skill: "name")`. Never read SKILL.md files manually or paste content into Agent prompts. No improvising. |
| [wiki-awareness](rules/wiki-awareness.md) | conditional | Consult or file knowledge when ingesting sources, answering questions, or producing reusable answers. |

## Skills

| Skill | Description |
|-------|-------------|
| [status](skills/status/SKILL.md) | User-facing `/status` health report — session context, container uptime, workspace mounts, tool availability, scheduled-task snapshot. Adopted from `nanoclaw-core` (core#68) so its workspace/mount/IPC detail only mounts in trusted and main containers. Complements `system-status` (orchestrator-DB probe), it does not replace it. |
| [system-status](skills/system-status/SKILL.md) | Read-only system-status probe for trusted-tier NanoClaw containers — surfaces stuck scheduled tasks, DB size, and recent task-run failures from the orchestrator's SQLite. Use as part of heartbeat or standalone. Renamed from `check-system-health` (which collided with the admin tile's same-named skill, per `nanoclaw-admin#65`); admin keeps the canonical full health probe with dismiss-mechanism management. |
| [trusted-memory](skills/trusted-memory/SKILL.md) | Session bootstrap and rolling memory updates for trusted containers. On session start, reads MEMORY.md (permanent facts), RUNBOOK.md (operational workflows), recent daily and weekly logs, and highlights.md to restore context. After non-trivial interactions, appends timestamped entries to group-local and cross-group shared daily logs. Use when starting a new session to load previous notes and remember context, or after meaningful conversations to save conversation history, persist session state, or record newly learned owner preferences. |
| [google-ops](skills/google-ops/SKILL.md) | Read-only Google Calendar and Tasks over the OneCLI gateway. [Trusted verification reference](skills/google-ops/references/trusted-verification.md) carries source selection and tier restrictions. |

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Development dependencies

`tessl.json` declares this repo's dev-time plugin dependencies.

- Every `jbaruch/*` dependency floats at `latest` (Runtime-Managed Manifest Carve-Out, `jbaruch/coding-policy: dependency-management`).
- `finsi/codex-review` is third-party and pins. No dependency scanner covers the tessl ecosystem. Renewal cadence: quarterly — run `tessl outdated` and bump the pin in its own commit.
