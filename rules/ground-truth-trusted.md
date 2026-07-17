---
alwaysApply: false
applyTo: "** — when answering substantive trusted-tier questions or producing claims that need verification"
---

# Ground Truth — Trusted Extensions

Extends the core ground-truth rule with verification methods available to trusted containers — native Google REST brokered by the OneCLI gateway for Google services (Calendar, Gmail, Tasks) and `gh` for GitHub.

## Additional verification sources

| Claim type | How to verify |
|------------|--------------|
| Calendar event | `google-calendar.py events-list` |
| Task/todo status | `google-tasks.py list` / `get` |
| Email content | The sanitizing Gmail-fetch path — `check-email`, `morning-brief`, `google-fetch` |
| GitHub PR/issue | `gh` — see the `github-data-via-gh` rule |

Op scripts mount at `/home/node/.claude/skills/tessl__heartbeat/scripts/<script>.py`. `jbaruch/nanoclaw-admin` `rules/google-access.md` is the authority for op names, arg conventions, and the Gmail-fetch exception — this rule does not restate them.

## Google needs the heartbeat mount

- No Google credential exists in the container; the gateway injects and refreshes the `Authorization: Bearer` on the wire.
- Never read a Google key from the environment or send an `Authorization` header yourself. A credential in the container is a bug, not a fallback.
- The op scripts ship in `nanoclaw-admin` — baseline on **main** only (`selectTiles`, `jbaruch/nanoclaw` `src/container-runner.ts`). A trusted non-main container reaches them only when `tessl__heartbeat` is co-loaded via its group's `containerConfig`.
- Scripts absent, or a call refused `access_restricted`: this container has no Google verification path. Report the claim as unverified — do not assert it, do not reach for another route.

## GitHub: `gh`-first, no non-existence claims on unauth 404

GitHub state — PRs, issues, repo contents, search results — comes from the authenticated `gh` CLI inside the container. For the full rationale and command shapes, see the `github-data-via-gh` rule.

A 404 from `curl https://api.github.com/...` proves "I cannot see this from this path", **not** that the resource does not exist. Owner-adjacent repos (`jbaruch/*`, `ligolnik/*`, `tessl-io/*`) may be private to the unauthenticated caller. Re-run the query through `gh` before asserting non-existence — and especially before retracting a prior statement about something existing on the strength of a 404.

**Sub-agent note:** Sub-agents spawned via `Agent` run inside the same container, inherit `GITHUB_TOKEN` from the env, and see the same script mounts, so both `gh` and the Google op scripts work inside them.

## Compute with external data

When a task requires external data, chain tools to compute the exact answer.

**Example:** "Remind me 15 minutes before I leave for Amir's pickup."

| Approach | Verdict |
|---|---|
| Ask "when do you leave?" | Wrong — you can compute it |
| Set it 15 min before the event start | Wrong — departure ≠ event start |
| Check calendar for destination → Maps for travel time → calculate real departure → set 15 min before | Correct |

These sources are not available in untrusted containers. The core ground-truth rule covers universal verification methods.
