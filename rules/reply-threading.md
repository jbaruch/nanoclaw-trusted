---
alwaysApply: true
---

# Reply Threading

## Required behavior

**Always reply-thread** user messages using `reply_to` on `mcp__nanoclaw__send_message`.

## Heartbeat matching contract

Heartbeat tracks unanswered messages by walking outbound IDs and matching each one's `reply_to` against the inbound queue. An outbound message without `reply_to` is invisible to the match.

## Scope

- Inbound user messages always
- Background-agent results always
- Scheduled-task output does not need `reply_to` — no user message to thread against
