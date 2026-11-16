---
alwaysApply: false
applyTo: "** — when answering substantive trusted-tier questions or producing claims that need verification"
---

# Ground Truth — Trusted Extensions

## Verification sources

- Calendar events: `google-calendar.py events-list`; tasks: `google-tasks.py list`/`get`.
- Invoke `Skill(skill: "google-ops")` or run scripts at `/home/node/.claude/skills/tessl__google-ops/scripts/<script>.py`.
- Email: use sanitizing Gmail-fetch skills. `jbaruch/nanoclaw-admin` `rules/google-access.md` owns op names, arguments, and the Gmail exception.
- GitHub: use authenticated `gh` per `github-data-via-gh`.

## Google boundaries

- The OneCLI gateway injects and refreshes authorization; no Google credential belongs in the container.
- Never read Google keys from the environment or send an `Authorization` header; a container credential is a bug, never a fallback.
- Calendar/Tasks scripts ship on main and trusted without admin co-loading. Trusted access is read-only: Calendar `events-list`; Tasks `list-tasklists`/`list`/`get`.
- Sanitizing Gmail-fetch ships in admin, baseline on main only. Trusted non-main has no email-verification path; report email claims as unverified, never raw-fetch.
- On `access_restricted`, report the claim unverified; do not assert it or try another route.

## GitHub and sub-agents

- An unauthenticated 404 proves only lack of visibility. Recheck through authenticated `gh` before asserting non-existence or retracting an existence claim.
- `Agent` sub-agents share the container, `GITHUB_TOKEN` and script mounts; `gh` and Google scripts work there.

## Compute with external data

- Chain tools to compute answers; do not ask for computable inputs.
- For departure reminders, use Calendar destination and Maps travel time to compute departure; subtract the reminder offset from departure, not event start.
- These sources are unavailable in untrusted containers; core ground-truth covers universal verification.
