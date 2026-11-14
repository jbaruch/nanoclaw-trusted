---
alwaysApply: false
applyTo: "** — when querying messages.db or referencing its column names"
---

# messages.db Schema

## Required Read

- Before querying `messages.db`, referencing its columns, or relying on a mutation exception, read `skills/system-status/references/messages-db-schema.md` in full.
- Its complete contract binds these actions.
- Resolve the reference within this installed plugin.
- Missing or unreadable content stops the affected action.
- Read explicitly when triggered; never `@`-import the reference.

## Boundary

- Use the reference for table shapes, access methods, mutation constraints, and schema drift.
