# 2026-04-27 — Dual-Handle Role-Splitting Incident

Reference incident motivating the deploy-tier `rules/identity-dual-handle.md` companion to the abstract dual-handle invariant in the `jbaruch/nanoclaw-core` tile's `rules/core-behavior.md`.

## What happened

- A debate-setup message addressed the agent by its display-name trigger, assigned debate positions to two other bots, and added a "you're the judge" instruction directed at the agent's Telegram `@username` — which is the SAME bot.
- The agent parsed the two surface forms as separate addressees and took on both the debater AND the judge roles in one turn.
- Owner correction confirmed the obvious: both handles point at the same bot.
- The same dual-handle pattern re-triggered the same morning on a follow-up message, confirming the failure mode wasn't a one-off parser glitch.

## Why this is in an ADR, not the rule

The runtime gate ("collapse trigger and `@username` into one addressee; never split into multiple roles based on surface form") is a per-turn behavior the rule keeps. The narrative — debate-setup wording, two re-triggers same morning, owner-correction wording — was loaded into every spawn but only fires the agent's recognition once the gate is already engaged. The ADR keeps the institutional memory; the rule keeps the gate.

## Companion mitigation outside the rule

The runtime identity preamble (`buildIdentityPreamble` in `jbaruch/nanoclaw-public`, injected from `ASSISTANT_NAME` / `ASSISTANT_USERNAME`) prevents the *identity-theft* form of dual-handle confusion (an agent claiming an example handle as its own). It does not stop the *role-splitting* form documented here. Both mitigations exist; this ADR is the one that documents the role-splitting failure class.
