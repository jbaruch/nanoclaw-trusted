---
alwaysApply: true
---

# Compaction-Aware Summaries

When Claude Code compacts context, the summary must preserve information that cannot be recovered from files alone.

## Compaction priorities

The summary MUST include, in this order:

1. **Personal facts** — Any preferences, family details, opinions, or personal context mentioned in this session that haven't been saved to trusted memory yet
2. **Decisions and reasoning** — What was decided, why, and what alternatives were rejected
3. **Commitments** — Promises made in both directions (what the owner committed to, what the assistant committed to deliver)
4. **Current task state** — What's being worked on, what step we're at, what's next
5. **New contacts or relationships** — Anyone mentioned for the first time with their context

## Pre-compaction save

If a personal fact was mentioned during the session but NOT yet saved to `/workspace/trusted/` memory — save it NOW, before compaction loses it. This is not optional. Compaction summaries are lossy; typed memory files are not.

## What compaction summaries naturally preserve (don't duplicate)

- File paths and code changes (these are in git)
- Tool call sequences (reconstructable from the task)
- Error messages (look at the code or logs)

Focus the summary budget on the human context that only exists in conversation.
