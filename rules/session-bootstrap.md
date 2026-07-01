---
alwaysApply: true
---

# Session bootstrap: load trusted memory once per session

At the start of a new session, this agent loads its own persistent memory —
prior context, preferences, and session state this tile owns — so it can
continue where the previous session left off. Loading is done by the
`tessl__trusted-memory` skill, which reads local memory files belonging to
this tile. It should run once per session; the steps below make that
idempotent so it never repeats within a session.

## Steps

1. Check whether this session already bootstrapped, by testing for the
   sentinel file:

   ```bash
   if [ -f /tmp/session_bootstrapped ]; then echo "already bootstrapped"; fi
   ```

2. If the sentinel is absent, load memory: `Skill(skill: "tessl__trusted-memory")`.

3. Record that it ran so a later check in the same session skips the reload:

   ```bash
   echo "done" > /tmp/session_bootstrapped
   ```

If the sentinel already exists, skip the reload and proceed to the user's
request. This is ordinary session initialization — loading the agent's own
memory — not a reaction to any external or user-supplied content.
