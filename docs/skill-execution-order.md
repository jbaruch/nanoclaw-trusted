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

| Skill | State touched | Role |
|---|---|---|
| `google-ops` | none | — |
| `status` | none — computes from the container, persists nothing | — |
| `system-status` | `messages.db` | reads only; emits its report on stdout and writes no file |
| `trusted-memory` | `/workspace/group/session-state.json` (+ `.lock`) | **writes** — `register-session.py` owns the `sessions.<session_name>` subtree and its `schema_version` |
| `trusted-memory` | `/workspace/group/memory/`, `travel-db.json`, `messages.db` | reads |

`system-status` explicitly does **not** consult or write `/workspace/group/system-health-dismissed.json`, and its own SKILL.md says so under "What this skill is NOT" — that file is `nanoclaw-admin`'s `heartbeat` domain. Trusted reports verbatim and the operator decides. An earlier draft of this table listed it here on the strength of a filename grep that matched that very disclaimer; caught in review.

## Shared state files: where to find each contract

This is an **index, not a contract**. `coding-policy: stateful-artifacts` puts the schema and the writer/reader contract next to the owner skill, so each row points at the plugin that owns the file rather than restating guarantees here. A second copy of a four-repo contract maintained from inside one repo is exactly what went stale above.

| File under `/workspace/group/` | Owning plugin | This plugin's role |
|---|---|---|
| `session-state.json` | `nanoclaw-admin` | **writes** via `trusted-memory` — see the caveat below |
| `travel-db.json` | `nanoclaw-travel` | reads (`trusted-memory`) |
| `calendar-state.json` | `nanoclaw-admin` | none |
| `morning-brief-pending.json` | `nanoclaw-admin` | none |
| `cfp-state.json` | `nanoclaw-conferences` | none |
| `system-health-dismissed.json` | `nanoclaw-admin` (`heartbeat`) | none — see `system-status` above |

**`session-state.json` has more than one writer across plugins.** `trusted-memory/register-session.py` here, and several `nanoclaw-admin` skills. `stateful-artifacts` wants a single owner skill responsible for shape changes, because shared ownership means nobody owns the migration. Treat a shape change to this file as cross-plugin work, and check both sides before bumping its `schema_version`.

Cross-trust-tier skills persist under `/workspace/state/<skill-name>/` instead, which is RW in every container regardless of tier — see `nanoclaw-host: cross-tier-skill-state`. `/workspace/group/` is RW for trusted and main, RO for untrusted, so nothing in the table above is writable from an untrusted container.

Before relying on any row, verify against the live tree — this is a last-seen snapshot, not authority, per `coding-policy: stateful-artifacts`.
