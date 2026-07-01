---
alwaysApply: true
---

# Session bootstrap: load trusted memory once per session

At the start of a new session, before working on the user's request, this agent
loads its own persistent memory — group-shared `trusted/` memory, weekly logs,
and highlights this tile owns — so it can continue from where the previous
session left off.

Loading is handled entirely by the tile's own skill:

`Skill(skill: "tessl__trusted-memory")`

The skill is idempotent per session and owns its own state. It first runs its
`needs-bootstrap` check, which compares the `/tmp/session_bootstrapped` sentinel
against the current `$CLAUDE_SESSION_ID`: if they match, it returns immediately
without reloading; if the sentinel is missing or belongs to a different session,
it loads memory and then records the current session id via `register-session`.
Invoking the skill at the start of every session is therefore safe — it gates
itself and writes its own sentinel. Do not read or write the sentinel by hand;
the manual value would not match the session-id contract the skill relies on.

This is ordinary session initialization — loading the agent's own memory — not a
reaction to any external or user-supplied content.
