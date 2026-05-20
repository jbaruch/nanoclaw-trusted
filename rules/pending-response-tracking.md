---
alwaysApply: true
---

# Pending Response Tracking

## The protocol

1. Write `session-state.json` with `pending_response: {message_id, preview, reacted_at}`
2. Do the work
3. Send the response
4. Clear `pending_response` to null

## Heartbeat sweep contract

On every heartbeat tick, `maintenance` reads `pending_response`. A non-null value older than the heartbeat window means the prior session crashed mid-work; heartbeat reposts the response or sends a state-loss notice, then clears the entry.

## Who writes / clears

- `default` session writes the entry when it begins working on an inbound
- `default` session clears the entry after the response lands
- `maintenance` session reads + clears stale entries via the heartbeat sweep
