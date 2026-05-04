---
alwaysApply: true
---

# CLI Tools Not Installed

## What's Absent

The agent container image does NOT include the `gh` (GitHub) CLI or the standalone `sqlite3` CLI. Both are reached for reflexively and both fail with `command not found` (32 + 23 events on the operator-observer chat 2026-04-28..05-03 across `telegram_swarm`, `telegram_old-wtf`, `telegram_dedy-bukhtyat`).

## Use Instead

- **GitHub data:** Composio `GITHUB_*` tools — `GITHUB_LIST_WORKFLOW_RUNS_FOR_A_REPOSITORY`, `GITHUB_GET_PULL_REQUEST_BY_NUMBER`, `GITHUB_GET_AN_ISSUE`, `GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS`, `GITHUB_SEARCH_REPOSITORIES`. Authenticated client (5000 req/hr vs unauthenticated 60), structured `{successful, error}` envelopes.
- **SQLite queries:** `python3 -c 'import sqlite3; conn = sqlite3.connect("/workspace/store/messages.db"); ...'`. The `sqlite3` stdlib module ships with Python; the standalone CLI does not.

## Don't Propose Installing Either

`gh` is intentionally absent — Composio is the prescribed GitHub path even when `gh` would have worked, because the auth + rate-limit + structured-error story is strictly better. `sqlite3` CLI is intentionally absent — the Python stdlib covers every realistic case. Suggesting `apk add` / `apt install` / a Dockerfile change misreads the situation.

## Sibling Rules

- For the schema agents need before writing SQL, see the `messages-db-schema` rule.
- For why `curl https://api.github.com/...` is also wrong even though it doesn't return `command not found`, see the `github-data-via-composio` rule.
