---
alwaysApply: true
---

# Reply Threading

## Required behavior

**Always reply-thread** user messages using `reply_to` on `mcp__nanoclaw__send_message`.

## Why it's required

Heartbeat tracks unanswered messages by walking outbound IDs and checking each one's `reply_to` against the inbound queue. A response that doesn't carry `reply_to` is invisible to that walk and flags the inbound as unanswered indefinitely.

## Scope

- Inbound user messages always
- Background-agent results always
- Scheduled-task output does not need `reply_to` — no user message to thread against
