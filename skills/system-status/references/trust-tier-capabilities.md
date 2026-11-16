# Trust-Tier Capability Matrix

The runtime mount layout is authoritative. Follow `container-trust-levels` for EROFS and `ground-truth-trusted` for Google verification boundaries. This reference describes capabilities, not permission to bypass a skill's read-only contract.

## Main and trusted

- Read/write group folder and `/workspace/trusted/` shared memory.
- Baseline plugins: core, trusted, and blog-writer; main also receives admin. Group configuration may add plugins; skill/rule blocklists may filter them.
- Calendar and Tasks read scripts ship in this plugin's `google-ops` skill on both main and trusted. The OneCLI gateway injects Google authorization; no container credential fallback is permitted.
- Sanitizing Gmail-fetch skills ship in admin, baseline on main only. Trusted non-main has no email-verification path under the loaded boundary.
- Host script execution and auto-memory are enabled.
- The host mounts `/workspace/store` writable for main/trusted; mount writability does not authorize reader mutations. See [messages-db-schema.md](messages-db-schema.md#shipped-readers) for the shipped reader contracts.
- Spawn limits: 1536 MB RAM, 2048 MB memory plus swap. No CPU cap is set by this tier branch.

## Untrusted

- Read-only group folder; no `/workspace/trusted/` mount.
- Core and untrusted baseline plugins.
- Google calls refused as `access_restricted`; no host scripts or auto-memory.
- Filtered per-chat database mounted read-only when available.
- Spawn limits: 512 MB RAM, no swap, one CPU, 256 PIDs, immutable root, 64 MB `/tmp` tmpfs.

## Runtime sources

Evidence pinned to `jbaruch/nanoclaw` commit `ef8cf4d6837427f8924deda83b7af00c215996fc`:

- [src/volume-mounts.ts](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/volume-mounts.ts#L453): `buildVolumeMounts` group/trusted/store mounts, skill materialization, auto-memory.
- [src/tile-materialize.ts](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/tile-materialize.ts#L10): `selectTiles` baseline plugins.
- [src/container-runner.ts](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/container-runner.ts#L267): tier-specific spawn limits.
- [src/config.ts](https://github.com/jbaruch/nanoclaw/blob/ef8cf4d6837427f8924deda83b7af00c215996fc/src/config.ts#L205): default `IDLE_TIMEOUT` is 1800000 ms (30 minutes). Inspect effective runtime configuration rather than assuming a tier-specific idle timeout.

Check the running host revision and update this reference alongside changes to these sources.
