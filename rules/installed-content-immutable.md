---
alwaysApply: true
---

# Installed Content Is Immutable At Runtime

Installed skills (`/home/node/.claude/skills/<name>/SKILL.md`) and rules (`/home/node/.claude/.tessl/...`) cannot be edited from inside the agent container. The kernel rejects writes to those paths with `EROFS` (jbaruch/nanoclaw#247).

## Why

Pre-fix, agents occasionally `Write`/`Edit` over their own installed `SKILL.md` files (under `skills/<name>/`) or per-tile rule markdowns (under `.tessl/tiles/<owner>/<tile>/rules/<rule>.md`) in-place. The changes never persisted past container restart (the orchestrator rebuilds `skills/` and `.tessl/` from the registry at the top of every spawn), but they were live for the current container's lifetime. That meant a session could operate on monkey-patched skills for minutes-to-hours and behave differently from what the registry actually serves — diagnoses got "wait, did the rule say X or Y?" and the answer depended on which container snapshot you were looking at.

Two read-only bind-mounts now layer on top of the writable `/home/node/.claude` parent so the kernel rejects any write to those subdirs at the syscall level. The agent's `Write`/`Edit` tools cannot patch installed content mid-session anymore.

## What's still writable

The parent `/home/node/.claude/` mount itself stays writable. The SDK keeps writing to:

- `projects/<slug>/<sessionId>.jsonl` — session transcripts
- `debug/`, `todos/`, `telemetry/`, `session-env/` — diagnostic state
- `projects/<slug>/memory/` — auto-memory overlay (trusted/main only)

Only `skills/` and `.tessl/` are read-only.

## How to actually change a skill or rule

Modifications must flow through the staging → promote → publish → update pipeline:

1. Edit the skill or rule in NAS staging (`groups/<group>/staging/<tile>/skills/<name>/SKILL.md` or `.../rules/<name>.md`).
2. Invoke `promote_to_tile_repo` (MCP tool) targeting the right tile. The promote pipeline opens a tile-repo PR, summons Copilot, and lands the change.
3. The tile's GHA `publish-tile.yml` workflow patches the version and publishes to the tessl registry on merge.
4. The next `./scripts/deploy.sh` runs `tessl update` inside the orchestrator and the new content lands at `/app/tessl-workspace/.tessl/tiles/...`.
5. Each subsequent agent-container spawn sees the new content (orchestrator's per-spawn cpSync rebuilds the per-group `skills/` and `.tessl/` from the registry).

## What "EROFS" looks like in practice

A `Write` against an installed skill returns:

```
sh: 1: cannot create /home/node/.claude/skills/<name>/SKILL.md: Read-only file system
```

This is not a bug to work around. It's the contract — go through the pipeline above instead.
