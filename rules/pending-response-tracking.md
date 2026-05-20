---
alwaysApply: true
---

# Pending Response Tracking

1. Write `session-state.json` with `pending_response: {message_id, preview, reacted_at}`
2. Do the work
3. Send the response
4. Clear `pending_response` to null

Heartbeat picks up interrupted responses.
