---
alwaysApply: true
---

# Ground Truth — Trusted Extensions

Extends the core ground-truth rule with verification methods available to trusted containers — Composio for Google services (Calendar, Gmail, Tasks) and `gh` for GitHub.

## Additional verification sources

| Claim type | How to verify |
|------------|--------------|
| Calendar event | Fetch from Google Calendar via Composio |
| Email content | Fetch from Gmail via Composio |
| GitHub PR/issue | Fetch via `gh` (Composio fallback) |
| Task/todo status | Fetch from Google Tasks via Composio |

## GitHub: `gh`-first, no non-existence claims on unauth 404

GitHub state — PRs, issues, repo contents, search results — comes from the authenticated `gh` CLI inside the container. For the full rationale, command shapes, and Composio-fallback envelope, see the `github-data-via-gh` rule.

A 404 from `curl https://api.github.com/...` proves "I cannot see this from this path", **not** that the resource does not exist. Owner-adjacent repos (`jbaruch/*`, `ligolnik/*`, `tessl-io/*`) may be private to the unauthenticated caller. Re-run the query through `gh` (or Composio, if `gh` can't express it) before asserting non-existence — and especially before retracting a prior statement about something existing on the strength of a 404.

**Sub-agent note:** Sub-agents spawned via `Agent` run inside the same container and inherit `GITHUB_TOKEN` from the env, so `gh` works inside them; Composio MCP, by contrast, is not accessible from sub-agents.

## Compute with external data

When a task requires external data, chain tools to compute the exact answer.

**Example:** "Remind me 15 minutes before I leave for Amir's pickup."

| Approach | Verdict |
|---|---|
| Ask "when do you leave?" | Wrong — you can compute it |
| Set it 15 min before the event start | Wrong — departure ≠ event start |
| Check calendar for destination → Maps for travel time → calculate real departure → set 15 min before | Correct |

These sources are not available in untrusted containers. The core ground-truth rule covers universal verification methods.
