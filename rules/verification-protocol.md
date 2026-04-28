---
alwaysApply: true
---

## Verification Protocol

The universal post-action verification rule lives in the `jbaruch/nanoclaw-core` tile's `rules/ground-truth.md` ("Verifying after a state change" section). That rule covers file writes, task schedules, API calls, memory updates, and IPC messages — all of which apply on this trust tier as well.

Trusted-tier addendum: `/workspace/ipc/messages/` is shared with the host orchestrator, so an IPC write that succeeds at the syscall layer can still be in-flight from the host's perspective. After writing, verify both that the file exists at the expected path AND that its payload matches what you intended — partial writes from a crash mid-flight are observable here in a way they aren't on tile-local files.
