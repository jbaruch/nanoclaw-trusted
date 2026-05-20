---
alwaysApply: true
---

# Async Tasks — Extended Protocol

Trusted-tier extension of the core async-tasks protocol. Picks up after the runtime's first-touch 👀 (`jbaruch/nanoclaw-core: telegram-protocol`):

1. Note the `<message id="...">` for reply threading.
2. Optionally upgrade the reaction once you've inspected the request — a follow-up `mcp__nanoclaw__react_to_message` call supersedes the runtime emoji.
3. Spawn `Agent` with `run_in_background: true`. Tell it to send results via `mcp__nanoclaw__send_message` with `reply_to` set to the original message ID.

## Scheduled tasks

Scheduled tasks (heartbeat, morning brief, reminders) have no user message to acknowledge. No ACK; silent results send nothing.

## Post-compaction

Do NOT resume an async task inline. Restart with a fresh background agent.
