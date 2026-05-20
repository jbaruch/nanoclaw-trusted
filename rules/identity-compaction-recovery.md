---
alwaysApply: true
---

# Identity — Compaction Recovery

## The trigger

After context compaction (the SDK summarizes prior turns), the agent's persona content is dropped from the visible context.

## Recovery action

Re-read `/workspace/global/SOUL.md`. This restores tone, communication style, and persona-specific behaviors that compaction stripped.

## When to re-read

- On the first turn after detecting a compaction event in the transcript
- On any turn where the agent notices it lacks persona context it would normally have
