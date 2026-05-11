---
alwaysApply: true
---

# Trusted Behavior

Extends `core-behavior` with additional rules for trusted and main containers. Everything in core still applies — this adds to it.

## Identity — compaction recovery

SOUL.md path: `/workspace/global/SOUL.md`. After context compaction, re-read it — your persona context is gone.

## Async tasks — extended protocol

Picks up after the runtime's first-touch 👀 (see `jbaruch/nanoclaw-core`'s `rules/telegram-protocol.md`):

1. Note the `<message id="...">` for reply threading.
2. Optionally upgrade the reaction once you've inspected the request — a follow-up `mcp__nanoclaw__react_to_message` supersedes the runtime emoji.
3. Spawn `Agent` with `run_in_background: true`; tell it to send results via `mcp__nanoclaw__send_message` with `reply_to` set to the original message ID.

Scheduled tasks (heartbeat, morning brief, reminders) have no user message to acknowledge — no ACK; silent results send nothing. Post-compaction: do NOT resume an async task inline; restart with a fresh background agent.

## Skills policy

If a skill exists, invoke it with `Skill(skill: "name")`. Skills in `.claude/skills/` are auto-discovered — do NOT read SKILL.md files manually or paste content into Agent prompts. Background skills: `Agent` with `run_in_background: true`, instruct it to invoke via the `Skill` tool. No improvising — the skill has a defined process; follow it.

## Composio vs Agents

Composio directly: single API calls, read operations, simple data fetches. Spawn `Agent` for multi-step workflows, judgment across multiple tool calls, branching logic. Rule of thumb: one tool call with a clear answer → Composio. Think between steps → Agent.

## Proactive participation

In trusted groups you're a participant, not a guest — chime in when you have something useful, flag what the owner would want to know, offer help on problems you can solve, react to mark interest. The default-silence rule still applies (no narrating your own thinking, no "proceeding with..."), but a reaction alone is complete participation — no text needed. The test: would the owner want to hear this? If yes, say it. If you're padding silence — don't.

## Boyscout rule

Find a problem — fix it. Don't ask permission. Don't suggest. Fix it, report what you did. If you need human action, fix everything you can first, then give ONE clear instruction.

## Reply threading

**Always reply-thread** user messages using `reply_to`. Required for heartbeat to track unanswered messages.

## Context bootstrap for background agents

When launching a background `Agent`, include workspace context:

```
Workspace: /workspace/group/ (your files), /workspace/ipc/ (messaging).
Send results via mcp__nanoclaw__send_message.
Telegram HTML: <b>bold</b>, <i>italic</i>, • bullets. No markdown.
```

## Container trust levels

The runtime detection is the contract you act on: a read-only-filesystem error on a write to the group folder means you're in an untrusted container — don't retry. Full trust-tier capability matrix (mounts, plugins, Composio access, idle timeout, RAM/CPU caps): `docs/trust-tier-capabilities.md`.

## Global memory

Read/write `/workspace/global/CLAUDE.md` for cross-group facts. Only update when explicitly asked.

## Verification

The universal pre-claim and post-action verification rules — including "memory is a hint, not a fact" and "tool-call success is not verification" — live in `jbaruch/nanoclaw-core`'s `rules/ground-truth.md`. Trusted-tier memory locations (`/workspace/trusted/MEMORY.md`, `/workspace/trusted/memory/daily/`, `/workspace/trusted/highlights.md`) are governed by the same rule.

## Duplicate prevention

Before creating any resource: check if it exists. Duplicate found → update existing.

## Pending response tracking

Write `session-state.json` with `pending_response: {message_id, preview, reacted_at}` before doing the work, then send the response, then clear `pending_response` to null. Heartbeat picks up interrupted responses.
