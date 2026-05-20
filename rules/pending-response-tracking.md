---
alwaysApply: true
---

# Pending Response Tracking

## The protocol

1. Write `session-state.json` with `pending_response: {message_id, preview, reacted_at}`
2. Do the work
3. Send the response
4. Clear `pending_response` to null

## What it protects against

Container crashes or restarts mid-work would otherwise leave the inbound message in limbo. Heartbeat reads `pending_response` on its next sweep and picks up interrupted responses, so the user always gets a reply or a state-loss notice.

## Who writes / clears

- `default` session writes the entry when it begins working on an inbound
- `default` session clears the entry after the response lands
- `maintenance` session reads + clears stale entries via the heartbeat sweep
