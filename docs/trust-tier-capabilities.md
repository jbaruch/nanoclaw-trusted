# Trust-Tier Capability Matrix

Reference for the runtime capabilities granted to each container trust tier. The runtime detection (read-only-filesystem error on a write to the group folder) is what the agent acts on per `rules/container-trust-levels.md` — this file is the on-demand expansion of what each tier actually allows.

## Main / Trusted

- Read/write group folder, `/workspace/trusted/` shared memory
- All plugins (core + trusted; admin if main)
- Composio API, host script execution
- Auto-memory enabled, 30 min idle timeout

## Untrusted

- Read-only group folder, no `/workspace/trusted/`
- Core + untrusted plugins only
- No Composio, no host scripts, no auto-memory
- 512MB RAM, 1 CPU, 5 min idle timeout

The authoritative source for this matrix is the host repo `jbaruch/nanoclaw` — specifically `src/container-runner.ts` (`buildVolumeMounts` for mount construction per tier; `selectTiles` for which tiles each tier installs) and the resource-limit constants applied to the container spawn. Update this doc alongside changes to those code paths.
