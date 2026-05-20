---
alwaysApply: true
---

# GitHub Data via `gh`

## What To Use

GitHub state — PRs, issues, repo contents, workflow runs, releases, search results — comes from the `gh` CLI inside the container. The orchestrator forwards `GITHUB_TOKEN` via `--env-file` (per `src/container-runner.ts` `SECRET_CONTAINER_VARS`, `jbaruch/nanoclaw#565`); `gh` reads it automatically, so no `gh auth login` is needed.

Always use `--json` to get structured output: `gh issue view 565 --repo jbaruch/nanoclaw --json title,body,state` parses cleanly. Without `--json`, output is human-formatted and brittle.

## Why Not `curl`

`curl https://api.github.com/...` doesn't return `command not found` — it appears to work, then quietly fails differently. The unauthenticated path's failure modes — 60 req/hr rate limit, no `{successful, error}` envelope, private-repo 404s indistinguishable from non-existence — are exactly what `gh` solves. Don't hand-roll `Authorization: Bearer "$GITHUB_TOKEN"` onto curl either; `gh` already does that correctly and exposes `--json` for parsing.

## Composio as Fallback Only

The Composio `GITHUB_*` tools (`COMPOSIO_MULTI_EXECUTE_TOOL` → `GITHUB_*`) remain reachable for the rare case `gh` can't express the operation. For the common cases — issue/PR view/edit/comment, workflow run listing, repo/file search, file content fetch — prefer `gh`. If a `gh` invocation appears to require Composio as a workaround, surface that gap explicitly instead of silently routing through Composio.

## Sub-Agents

Sub-agents spawned via `Agent` run inside the same container and inherit `GITHUB_TOKEN` from the env, so `gh` works inside them. Composio MCP, by contrast, is not accessible from sub-agents — another reason to prefer `gh`.

## Sibling Rules

- The standalone `sqlite3` CLI is also absent from the container image (separate concept) — see the `messages-db-schema` rule for the `python3 -c 'import sqlite3'` path.
