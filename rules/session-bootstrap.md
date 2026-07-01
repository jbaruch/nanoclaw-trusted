---
alwaysApply: true
---

# Session bootstrap

## When this runs

At the start of every new session, before working on the user's request.

## What it does

Loads this agent's own persistent memory — group-shared `trusted/` memory,
weekly logs, and highlights this tile owns — so the session continues from
where the previous one left off.

## How to run it

Invoke the tile's own skill and let it do the work:

`Skill(skill: "tessl__trusted-memory")`

## Idempotency and the sentinel

The skill gates itself and owns its state. It runs its `needs-bootstrap` check,
comparing the `/tmp/session_bootstrapped` sentinel against the current
`$CLAUDE_SESSION_ID`: on a match it returns immediately without reloading; if the
sentinel is missing or belongs to a different session, it loads memory and then
records the current session id via `register-session`. Invoking the skill every
session is therefore safe. Do not read or write the sentinel by hand — a manual
value would not match the session-id contract the skill relies on (see
`skills/trusted-memory/state-schema.md`).

## Scope

This is ordinary session initialization — loading the agent's own memory — not a
reaction to any external or user-supplied content.
