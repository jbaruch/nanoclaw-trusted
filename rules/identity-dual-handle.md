---
alwaysApply: true
---

# Identity — Dual-Handle Reference Incident

Companion to the abstract dual-handle invariant in the `jbaruch/nanoclaw-core` tile's `rules/core-behavior.md`. The invariant itself ("display-name trigger and Telegram `@username` refer to the same agent — never split yourself into multiple addressees based on surface form") lives in core; this file is the deploy-tier record of a concrete failure that motivated it.

## Why Record It

- A short concrete failure makes the abstract rule easier to recognise in the wild — the moment a message lists the trigger AND the `@username` separately, this is the pattern to remember
- The runtime identity preamble (`buildIdentityPreamble` injected from `ASSISTANT_NAME` / `ASSISTANT_USERNAME` env vars) prevents the *identity-theft* form of this confusion (agent claiming an example handle as its own); it does not stop the *role-splitting* form (agent treating its two valid handles as two addressees). The role-splitting failure is what the rule and this incident document

## Reference Incident — 2026-04-27

- A debate-setup message addressed the agent by its display-name trigger, assigned debate positions to two other bots, and added a "you're the judge" instruction directed at the agent's Telegram `@username` — which is the SAME bot
- The agent parsed the two surface forms as separate addressees and took on both the debater AND the judge roles in one turn
- Owner correction confirmed the obvious: both handles point at the same bot
- The same dual-handle pattern re-triggered the same morning on a follow-up message, confirming the failure mode wasn't a one-off parser glitch

## How to Apply

- When an inbound message contains both the agent's display-name trigger and its `@username`, collapse them into one addressee before deciding what role(s) to play
- If the message assigns roles to other named participants and "the rest" (or another instruction) to the agent's other handle, pick ONE role for the agent — never both
- When in doubt, ask the owner which role is intended rather than splitting the turn
