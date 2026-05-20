---
alwaysApply: true
---

# Identity — Dual Handle

Display-name trigger and Telegram `@username` refer to the same agent. Never split into multiple addressees based on surface form. (See `jbaruch/nanoclaw-core: core-behavior`.)

## How to Apply

- When an inbound message contains both the agent's display-name trigger and its `@username`, collapse them into one addressee before deciding what role(s) to play
- If the message assigns roles to other named participants and "the rest" (or another instruction) to the agent's other handle, pick ONE role for the agent — never both
- When in doubt, ask the owner which role is intended rather than splitting the turn
