---
alwaysApply: false
applyTo: "** — when learning something new worth recording in daily_discoveries.md"
---

# Daily Discoveries Rule

When you learn something new and operationally important — a workflow, where something lives, how something works, a tool to use for a specific task — immediately record it via the `append-daily-discovery.py` script:

```
python3 /home/node/.claude/skills/tessl__trusted-memory/scripts/append-daily-discovery.py \
    --what "<one-line description of what you learned>" \
    --context "<how you found out / what prompted this>" \
    --promote-to "<RUNBOOK.md | typed memory file + MEMORY.md index | unsure>"
```

The script appends a block in this canonical shape to `/workspace/trusted/memory/daily_discoveries.md`:

## YYYY-MM-DD HH:MM UTC
**What:** [one-line description of what you learned]
**Context:** [how you found out / what prompted this]
**Promote to:** [RUNBOOK.md / typed memory file + MEMORY.md index / unsure]

Script behavior:

- Holds `fcntl.LOCK_EX` on a sibling `<file>.lock` for the entire read-modify-write cycle.
- Atomic-writes via tempfile + fsync + `os.replace`.
- Skips the write when the candidate block normalizes to an entry already in the file.
- Stdout: single-line JSON `{path, appended, dropped_duplicate, created, timestamp}`.
- Override the target path via `--discoveries-file` or `NANOCLAW_DISCOVERIES_FILE` env var.

Do this immediately when learned, not at end of session. This ensures the knowledge survives context compaction.
