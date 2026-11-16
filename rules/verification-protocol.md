---
alwaysApply: true
---

## Verification Protocol

The universal post-action verification rule lives in the `jbaruch/nanoclaw-core` tile's `rules/ground-truth.md` ("Verifying after a state change" section). That rule covers file writes, task schedules, API calls, memory updates, and IPC messages — all of which apply on this trust tier as well.

Trusted-tier addendum: after writing under `/workspace/ipc/messages/`, verify that the file exists at the expected path AND read back the file to verify its payload matches what you intended.
