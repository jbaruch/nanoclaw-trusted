---
alwaysApply: true
---

# Session bootstrap

## When

- Run at the start of every session, before the user's request.

## Action

- Invoke `Skill(skill: "tessl__trusted-memory")`.
- Loads group-shared `trusted/` memory, weekly logs, and `highlights.md`.

## Sentinel ownership

- The skill runs `needs-bootstrap` and `register-session` itself.
- Sentinel `/tmp/session_bootstrapped` stores the current `$CLAUDE_SESSION_ID`.
- Re-bootstrap on a missing or mismatched sentinel; skip on a match.
- Do NOT read or write the sentinel by hand.
- A hand-written value does NOT satisfy the session-id contract.

## Reference

- Sentinel and state shape: `skills/trusted-memory/state-schema.md`.
