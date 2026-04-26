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

## Compute with external data

When a task requires external data, chain tools to compute the exact answer.

**Example:** "Remind me 15 minutes before I leave for Amir's pickup."

| Approach | Verdict |
|---|---|
| Ask "when do you leave?" | Wrong — you can compute it |
| Set it 15 min before the event start | Wrong — departure ≠ event start |
| Check calendar for destination → Maps for travel time → calculate real departure → set 15 min before | Correct |

These sources are not available in untrusted containers. The core ground-truth rule covers universal verification methods.
