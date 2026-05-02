---
alwaysApply: true
---

# Installed Content Is Immutable At Runtime

Installed skills (`/home/node/.claude/skills/<name>/SKILL.md`) and per-tile rule markdowns (`/home/node/.claude/.tessl/...`) cannot be edited from inside the agent container. Two read-only bind-mounts layer on top of the writable `/home/node/.claude` parent; the kernel rejects writes to those subdirs at the syscall level. A `Write` returns `cannot create <path>: Read-only file system` — that's the contract, not a bug. See `docs/adr/2026-04-25-installed-content-erofs.md` for the motivating incident (`jbaruch/nanoclaw#247`) and the staging → promote → publish → update pipeline that's the supported way to change a skill or rule.

## What's still writable

The parent `/home/node/.claude/` mount stays writable. The SDK keeps writing to `projects/<slug>/<sessionId>.jsonl` (transcripts), `debug/`, `todos/`, `telemetry/`, `session-env/`, and `projects/<slug>/memory/` (auto-memory overlay, trusted/main only). Only `skills/` and `.tessl/` are read-only.
