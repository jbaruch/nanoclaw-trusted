---
alwaysApply: true
---

# Global Memory

## What it is

`/workspace/global/CLAUDE.md` carries cross-group facts that every trusted/main container should see.

## Read access

All trusted and main containers can read. Use as the source of truth for owner-wide facts (work patterns, multi-group context, identity continuity).

## Write access

Only update when explicitly asked. Edits are durable across every group's next session.
