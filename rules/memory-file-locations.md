---
alwaysApply: true
---

# Memory File Locations

## Directory structure

| Path | Contents |
|------|----------|
| `/workspace/trusted/` (root) | All typed memory files: `user_*.md`, `feedback_*.md`, `project_*.md`, `reference_*.md`, `key-people.md` |
| `/workspace/trusted/MEMORY.md` | Index file — one-line pointers to memory files in the root |
| `/workspace/trusted/memory/daily/` | Daily log files (auto-managed by trusted-memory skill) |
| `/workspace/trusted/memory/daily_discoveries.md` | Append-only discovery log |
| `/workspace/trusted/wiki/` | Wiki pages (domain knowledge, not operational memory) |
| `/workspace/trusted/sources/` | Raw source materials for wiki |
| `/workspace/trusted/highlights.md` | Weekly highlights archive |

## Rules

1. **All typed memory files go in `/workspace/trusted/` root** — never in `/workspace/trusted/memory/`. The `memory/` subdirectory is ONLY for daily logs and daily_discoveries.
2. **Every memory file must be indexed in MEMORY.md** — if a file exists in root but isn't in the index, it's an orphan. Fix by adding an index entry.
3. **MEMORY.md paths must match actual file locations** — if the index points to `memory/foo.md` but the file is at root `foo.md`, the index is wrong.
4. **No duplicate files** — a memory file exists in exactly one location. If you find the same file in both `/workspace/trusted/` and `/workspace/trusted/memory/`, delete the one in `memory/`.

## Common mistake

Creating feedback files in `/workspace/trusted/memory/feedback_*.md` instead of `/workspace/trusted/feedback_*.md`. The `memory/` prefix feels natural but is wrong — only `daily/` content goes there.
