---
alwaysApply: true
---

# Container Trust Levels

## The runtime contract

The runtime's mount layout is the contract. A read-only-filesystem error on a write to the group folder means you're in an untrusted container.

## Don't retry on EROFS

If a write to `/workspace/group/` fails with `EROFS` / "Read-only file system", do NOT retry. The mount is intentionally RO; the retry will fail the same way.

## Full capability matrix

The full trust-tier capability matrix (mounts, plugins, Google access, idle timeout, RAM/CPU caps) lives in `docs/trust-tier-capabilities.md`.

## Google verification boundaries

- Never read a Google key from the environment or send an `Authorization` header yourself. A credential in the container is a bug, not a fallback.
- Email content is the exception: the sanitizing Gmail-fetch skills ship only in `nanoclaw-admin` (baseline on **main** only). A trusted non-main container has no email-verification path — report an email claim as unverified there rather than reaching for a raw fetch.
- A call refused `access_restricted` (untrusted tier, gated by design): this container has no Google verification path. Report the claim as unverified — do not assert it, do not reach for another route.
- Before trusted-service verification, read `skills/google-ops/references/trusted-verification.md` in full within this installed plugin.
- Missing or unreadable content stops verification; read explicitly, never `@`-import it.
