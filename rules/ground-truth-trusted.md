---
alwaysApply: true
---

# Ground Truth — Trusted Extensions

Extends the core ground-truth rule with verification methods and computation available to trusted containers via Composio.

## Additional verification sources

| Claim type | How to verify |
|------------|--------------|
| Calendar event | Fetch from Google Calendar via Composio |
| Email content | Fetch from Gmail via Composio |
| GitHub PR/issue | Fetch from GitHub via Composio |
| Task/todo status | Fetch from Google Tasks via Composio |

## GitHub: Composio-first, no non-existence claims on unauth 404

GitHub state — PRs, issues, repo contents, search results — must come through Composio's GitHub tools (`GITHUB_GET_A_PULL_REQUEST`, `GITHUB_GET_A_REPOSITORY`, `GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS`, `GITHUB_GET_FILE_CONTENT`, etc.) invoked via `mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL`. Unauthenticated `curl https://api.github.com/...` is the wrong primary path for any owner-adjacent repo (`jbaruch/*`, `ligolnik/*`, `tessl-io/*`, and similar — assume those may be private to the unauthenticated caller).

A 404 from unauth curl proves "I cannot see this from this path", **not** that the resource does not exist. Re-run the query through Composio before asserting non-existence — and especially before retracting a prior statement about something existing on the strength of a 404. Curl is a fallback only: confirmed-public repos, HTTP-status diagnostics where auth is immaterial, or a Composio rate-limit failover.

**Sub-agent caveat:** Sub-agent containers spawned via `Agent` do not have Composio MCP access. If a sub-agent needs GitHub state, fetch it in the parent agent first and pass via prompt.

## Compute with external data

When a task requires external data, chain tools to compute the exact answer.

**Example:** "Remind me 15 minutes before I leave for Amir's pickup."

| Approach | Verdict |
|---|---|
| Ask "when do you leave?" | Wrong — you can compute it |
| Set it 15 min before the event start | Wrong — departure ≠ event start |
| Check calendar for destination → Maps for travel time → calculate real departure → set 15 min before | Correct |

These sources are not available in untrusted containers. The core ground-truth rule covers universal verification methods.
