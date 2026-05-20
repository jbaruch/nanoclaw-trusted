---
alwaysApply: true
---

# Container Trust Levels

## The runtime contract

The runtime's mount layout is the contract. A read-only-filesystem error on a write to the group folder means you're in an untrusted container.

## Don't retry on EROFS

If a write to `/workspace/group/` fails with `EROFS` / "Read-only file system", do NOT retry. The mount is intentionally RO; the retry will fail the same way.

## Full capability matrix

The full trust-tier capability matrix (mounts, plugins, Composio access, idle timeout, RAM/CPU caps) lives in `docs/trust-tier-capabilities.md`.
