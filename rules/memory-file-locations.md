---
alwaysApply: true
---

# Memory File Locations

Typed memory files (`user_*.md`, `feedback_*.md`, `project_*.md`, `reference_*.md`, `key-people.md`) live in `/workspace/trusted/` root — NOT in `/workspace/trusted/memory/`. The `memory/` subdirectory is reserved for `daily/` logs and `daily_discoveries.md`. `MEMORY.md` (also at root) is the index — one-line pointers to each typed file. `highlights.md` (root) is the weekly archive. Wiki content (`wiki/`, `sources/`) is separate from operational memory and not governed by this rule.

## Invariants

1. Every typed memory file at root MUST have an entry in `MEMORY.md` — orphans get an index entry added.
2. `MEMORY.md` paths MUST resolve — if the index points to `memory/foo.md` but the file is at root `foo.md`, fix the index, not the file location.
3. No duplicates — a memory file exists in exactly one location. If the same file appears in both root and `memory/`, delete the `memory/` copy.

## Common mistake

Creating `feedback_*.md` under `/workspace/trusted/memory/` instead of `/workspace/trusted/`. The `memory/` prefix feels natural but only `daily/` content goes there.
