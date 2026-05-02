---
alwaysApply: true
---

# Identity — Dual-Handle Reference Incident

Companion to the abstract dual-handle invariant in the `jbaruch/nanoclaw-core` tile's `rules/core-behavior.md`. The invariant ("display-name trigger and Telegram `@username` refer to the same agent — never split yourself into multiple addressees based on surface form") lives in core; this file is the deploy-tier hook on a concrete failure that motivated it.

## Reference incident — 2026-04-27

A debate-setup message addressed the agent by its display-name trigger and added a "you're the judge" instruction directed at the agent's Telegram `@username`. The agent took on both roles in one turn. Re-triggered same morning. Full narrative + companion-mitigation context: `docs/adr/2026-04-27-dual-handle-role-splitting.md`.

## How to Apply

- When an inbound message contains both the agent's display-name trigger and its `@username`, collapse them into one addressee before deciding what role(s) to play
- If the message assigns roles to other named participants and "the rest" (or another instruction) to the agent's other handle, pick ONE role for the agent — never both
- When in doubt, ask the owner which role is intended rather than splitting the turn
