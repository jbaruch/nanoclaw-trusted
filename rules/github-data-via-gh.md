---
alwaysApply: false
applyTo: "** — when reading GitHub data via the gh CLI"
---

# GitHub Data via `gh`

## What To Use

GitHub state — PRs, issues, repo contents, workflow runs, releases, search results — comes from the `gh` CLI inside the container. The orchestrator forwards `GITHUB_TOKEN` via `--env-file` (per `src/container-runner.ts` `SECRET_CONTAINER_VARS`, `jbaruch/nanoclaw#565`); `gh` reads it automatically, so no `gh auth login` is needed.

Always use `--json` to get structured output: `gh issue view 565 --repo jbaruch/nanoclaw --json title,body,state` parses cleanly. Without `--json`, output is human-formatted and brittle.

## Why Not `curl`

Don't use `curl https://api.github.com/...` for GitHub data — the unauthenticated path appears to work, then quietly fails. Known failure modes:

- 60 req/hr rate limit
- No `{successful, error}` envelope
- Private-repo 404s indistinguishable from non-existence

Don't hand-roll `Authorization: Bearer "$GITHUB_TOKEN"` onto curl either. Use `gh --json`.

## No Fallback

`gh` is the only path to GitHub data — there is no second route to fall back on. If an operation appears to be one `gh` can't express, surface that gap explicitly rather than hand-rolling a substitute.

## Sub-Agents

Sub-agents spawned via `Agent` run inside the same container and inherit `GITHUB_TOKEN` from the env, so `gh` works inside them.

## Sibling Rules

- The standalone `sqlite3` CLI is also absent from the container image (separate concept) — see the `messages-db-schema` rule for the `python3 -c 'import sqlite3'` path.
