---
alwaysApply: true
---

# GitHub Data via Composio

## Direct curl Is Wrong Too

`curl https://api.github.com/...` doesn't return `command not found` (the `cli-tools-not-installed` rule's territory) — it appears to work, then quietly fails differently. 49 distinct curl-against-`api.github.com` command shapes on the operator-observer chat 2026-04-28..05-03 (all in `telegram_old-wtf`) all hit the unauthenticated public-API path and probed more URLs to triangulate after each 404.

## Why It Fails

- 60 req/hr unauthenticated rate limit (vs 5000 with the operator's authenticated Composio client).
- No structured error envelope — the agent has to parse curl exit codes + raw HTTP status instead of `{successful: false, error: "..."}`.
- Silent visibility gap — private repos and fork structure look different from what the operator's authenticated session sees, so guessed slug probes 404 even when the real resource exists.

## What To Use

The Composio `GITHUB_*` tools enumerated in the `cli-tools-not-installed` rule. If a specific endpoint isn't covered by an existing tool, surface that gap explicitly — don't reach for `curl` as the workaround. The most common missing-tool scenario gets solved by `GITHUB_SEARCH_REPOSITORIES` or `GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS`, which resolve fork-name lookups in one shot rather than the N-curl-probe pattern that surfaced the audit.

## Don't Hand-Roll Authentication

The unauthenticated curl path is not solvable by adding `Authorization: Bearer ...` to the curl invocation — there's no PAT in the container, by design (per `coding-policy: no-secrets`). Composio holds the authenticated client; the agent calls Composio.
