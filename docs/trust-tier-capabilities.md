# Trust-Tier Capability Matrix

Reference for the runtime capabilities granted to each container trust tier. The runtime detection (read-only-filesystem error on a write to the group folder) is what the agent acts on per `rules/container-trust-levels.md` — this file is the on-demand expansion of what each tier actually allows.

## Main / Trusted

- Read/write group folder, `/workspace/trusted/` shared memory
- All plugins (core + trusted; admin if main)
- Google (Calendar, Gmail, Tasks, Drive) over native REST, brokered by the OneCLI gateway — the gateway injects and refreshes the OAuth Bearer on the wire, so no Google credential sits in the container
- Host script execution
- Auto-memory enabled, 30 min idle timeout

The gateway grants Google to both tiers, but the op scripts that call it ship in `nanoclaw-admin` (`skills/heartbeat/scripts/`) — baseline on main only. A trusted non-main container has a Google-capable gateway and no scripts to drive it unless `tessl__heartbeat` is co-loaded via its group's `containerConfig`.

## Untrusted

- Read-only group folder, no `/workspace/trusted/`
- Core + untrusted plugins only
- No Google access — OneCLI `secretMode` is `selective`, so Google calls are refused `access_restricted` by design (`jbaruch/nanoclaw#638`); no host scripts, no auto-memory
- 512MB RAM, 1 CPU, 5 min idle timeout

The authoritative source for this matrix is the host repo `jbaruch/nanoclaw` — specifically `src/container-runner.ts` (`buildVolumeMounts` for mount construction per tier; `selectTiles` for which tiles each tier installs) and the resource-limit constants applied to the container spawn. Update this doc alongside changes to those code paths.
