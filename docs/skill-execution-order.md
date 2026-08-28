# Shared State and Cross-Repo Skill Chains

Reference for skill authors touching state this plugin shares with other plugins in the fleet. Read it on demand when modifying a skill that reads or writes one of the files below; it is not always-loaded into the agent prefix, and `docs/` is `.tesslignore`d so it does not ship.

The contents began as the always-loaded `rules/skill-dependencies.md` rule, moved here by `jbaruch/nanoclaw-admin#180` (RULES.md diet).

## This plugin runs no cron chains

`nanoclaw-trusted` ships four skills — `google-ops`, `status`, `system-status`, `trusted-memory` — and **none declares `cadence:` frontmatter**. There is no scheduled chain in this repo to document.

The earlier version of this file narrated step-numbered `heartbeat` / `morning-brief` / `nightly-housekeeping` chains. Every skill in those narratives has since moved out or ceased to exist, so the narratives were re-derived away rather than renumbered:

| Skill in the old narrative | Where it lives now |
|---|---|
| `heartbeat`, `morning-brief`, `check-calendar` | `jbaruch/nanoclaw-admin` |
| `check-travel-bookings` | `jbaruch/nanoclaw-travel` |
| `check-cfps` | `jbaruch/nanoclaw-conferences` |
| `check-watchlist` | `jbaruch/nanoclaw-media` |
| `check-orders` | gone — overlay retired by `jbaruch/nanoclaw#935` |
| `nightly-housekeeping` | gone — split into 11 sub-skills by `jbaruch/nanoclaw#404` |
| `task-tz-sync` | gone — no repo in the fleet ships it |

A chain that spans four repos cannot be kept current from inside one of them, which is how the previous narrative went stale under its own currency note. Each owning repo documents its own cadence; the registry materialises them into `scheduled_tasks` rows, which is the authoritative live view:

```sql
SELECT id, schedule FROM scheduled_tasks WHERE source = 'cadence-registry';
```

## What this plugin's skills touch

| Skill | State touched |
|---|---|
| `google-ops` | none |
| `status` | none — computes from the container, persists nothing |
| `system-status` | `/workspace/group/system-health-dismissed.json`, `messages.db` |
| `trusted-memory` | `/workspace/group/memory/`, `/workspace/group/session-state.json` (+ `.lock`), `travel-db.json`, `messages.db` |

## Shared state files, and who owns them

Reader/writer contract for the files this plugin shares. Owner counts are skill files referencing each path, per repo.

| File | Owning plugin | Also read by |
|------|---------------|--------------|
| `/workspace/group/session-state.json` | `nanoclaw-admin` (8) | `nanoclaw-trusted` (3) |
| `/workspace/group/travel-db.json` | `nanoclaw-travel` (15) | `nanoclaw-admin` (1), `nanoclaw-trusted` (1) |
| `/workspace/group/calendar-state.json` | `nanoclaw-admin` (4) | — |
| `/workspace/group/morning-brief-pending.json` | `nanoclaw-admin` (12) | — |
| `/workspace/group/cfp-state.json` | `nanoclaw-conferences` (19) | `nanoclaw-admin` (5) |
| `/workspace/group/system-health-dismissed.json` | `nanoclaw-trusted` | — |

Cross-trust-tier skills persist under `/workspace/state/<skill-name>/` instead, which is RW in every container regardless of tier — see `nanoclaw-host: cross-tier-skill-state`. `/workspace/group/` is RW for trusted and main, RO for untrusted, so a file in the table above is not writable from an untrusted container.

Before relying on any row here, verify against the live tree — this is a last-seen snapshot, not authority, per `coding-policy: stateful-artifacts`.
