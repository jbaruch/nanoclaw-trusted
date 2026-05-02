# 2026-04-25 — Installed Content EROFS (jbaruch/nanoclaw#247)

Reference for the read-only contract on `/home/node/.claude/skills/` and `/home/node/.claude/.tessl/` enforced by `rules/installed-content-immutable.md`.

## Why the contract exists

- Pre-fix, agents occasionally `Write`/`Edit` over their own installed `SKILL.md` files or rule markdowns in-place.
- Changes never persisted past container restart (the orchestrator rebuilds `skills/` and `.tessl/` from the registry at the top of every spawn) but were live for the current container's lifetime.
- A session could operate on monkey-patched content for minutes-to-hours, producing diagnoses that didn't match what the registry actually served.

## How the kernel enforces it

Two read-only bind-mounts layer on top of the writable `/home/node/.claude` parent. Writes against `skills/` or `.tessl/` return a standard `cannot create <path>: Read-only file system` error at the syscall level — the rejection is the contract, not a bug to work around.

## How to actually change a skill or rule

Modifications flow through the staging → promote → publish → update pipeline:

1. Edit the skill or rule in NAS staging (`groups/<group>/staging/<tile>/skills/<name>/SKILL.md` or `.../rules/<name>.md`).
2. Invoke `tessl__promote-tiles` (the same admin-side skill `no-orphan-tasks.md` references) targeting the right tile. The skill opens a tile-repo PR, summons Copilot, and iterates fixups via `push_staged_to_branch` until the PR merges.
3. The tile's GHA `publish-tile.yml` patches the version and publishes to the tessl registry on merge.
4. The next `./scripts/deploy.sh` runs `tessl update` and the new content lands at `/app/tessl-workspace/.tessl/tiles/...`.
5. Each subsequent agent-container spawn sees the new content (orchestrator's per-spawn cpSync rebuilds `skills/` and `.tessl/` from the registry).

## What stays writable

The parent `/home/node/.claude/` mount stays writable. The SDK keeps writing to `projects/<slug>/<sessionId>.jsonl` (transcripts), `debug/`, `todos/`, `telemetry/`, `session-env/`, and `projects/<slug>/memory/` (auto-memory overlay, trusted/main only). Only `skills/` and `.tessl/` are read-only — the agent's own state surfaces are unaffected.
