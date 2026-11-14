---
alwaysApply: true
---

# Session bootstrap

## When

- Scheduled-task prompts start with the host prefix `[SCHEDULED TASK -`.
- Interactive sessions bootstrap before the user's request.

## Action

- For scheduled-task prompts, the first tool call is the task skill, with no bootstrap reads.
- After the task skill, invoke `Skill(skill: "tessl__trusted-memory")` Step 1 for registration only.
- For interactive sessions, invoke `Skill(skill: "tessl__trusted-memory")` Step 1 to load group-shared `trusted/` memory, weekly logs, and `highlights.md`.

## Sentinel ownership

- The skill owns the sentinel check and the single `register-session.py` call; scheduled prompts skip the check.
- Sentinel `/tmp/session_bootstrapped` stores the resolved current session identity; its lookup contract is in the state-shape reference below.
- For interactive sessions, re-bootstrap on a missing or mismatched sentinel; skip on a match.
- Do NOT read or write the sentinel by hand.
- A hand-written value does NOT satisfy the session-id contract.

## Reference

- Sentinel and state shape: `skills/trusted-memory/state-schema.md`.
