---
name: google-ops
description: "Native Google Calendar and Tasks reads over the OneCLI gateway, for trusted-tier ground-truth verification. Run google-calendar.py events-list to read the owner's calendar, or google-tasks.py list-tasklists / list / get to read task lists and task status. The OneCLI gateway injects the Bearer on the wire — no Google credential in the container. Gmail is intentionally excluded. Use when a trusted agent must verify a calendar event or a task/todo status, or otherwise read the owner's Calendar or Tasks."
user-invocable: false
---

# Google Ops Skill

This skill is an action router — pick the step that matches the read you need and execute only that step. Do not run other steps; do not parallelize.

Scripts mount at `/home/node/.claude/skills/tessl__google-ops/scripts/`. No Google credential lives in this container: the OneCLI gateway injects the `Authorization: Bearer` on the wire and refreshes it. Never send an `Authorization` header or read a Google key from the environment — a credential in the container is a bug, not a fallback.

Each script is a black box per `coding-policy: script-as-black-box` — the endpoint, defaults, query encoding, and output shape live in its top-of-file docstring. `jbaruch/nanoclaw-admin` `rules/google-access.md` is the authority for op names and argument conventions; this skill does not restate them. Argument computation (time windows, timezone math, which tasklist) stays with the caller — it is reasoning, not a fixed transform.

**Read-only.** This skill exposes reads only: calendar `events-list` and tasks `list-tasklists` / `list` / `get`. The task-mutation ops (`patch` / `insert` / `delete`) are admin-tier-only and are not present in this tile's `google-tasks.py` — a trusted agent cannot write to the owner's tasks through this skill.

## Step 1 — Read calendar events

Reads the owner's calendar. Pipe a JSON object of native Calendar query params on stdin (`timeMin`/`timeMax` as `...Z` UTC, `orderBy`, etc.); empty stdin applies the defaults (`primary` calendar, `singleEvents=true`). Events come back in top-level `items`.

```bash
echo '{"timeMin": "2026-07-18T00:00:00Z", "timeMax": "2026-07-19T00:00:00Z", "orderBy": "startTime"}' \
  | python3 /home/node/.claude/skills/tessl__google-ops/scripts/google-calendar.py events-list
```

Exit 0 with the raw Calendar resource on stdout is success. A non-zero exit prints only a stderr diagnostic and no stdout — surface the failure and stop, do not act on absent data. Finish here.

## Step 2 — Read task lists and task status

Reads task lists and tasks. `list-tasklists` takes empty stdin; `list` needs `{"tasklist_id": "..."}`; `get` needs `{"tasklist_id": "...", "task_id": "..."}`. Arrays come back in top-level `items`; `get` returns the task resource itself.

```bash
echo '{}' | python3 /home/node/.claude/skills/tessl__google-ops/scripts/google-tasks.py list-tasklists
echo '{"tasklist_id": "<id>"}' | python3 /home/node/.claude/skills/tessl__google-ops/scripts/google-tasks.py list
```

Exit 0 with the raw Tasks resource on stdout is success. A non-zero exit prints only a stderr diagnostic and no stdout. Finish here.

## Step 3 — Handle a tier or gateway refusal

Both scripts exit non-zero with a stderr diagnostic on failure. Two shapes are not transient and must not be retried:

- **`unauthenticated` / gateway not injecting (Google 401)** — the gateway is off this request path or the Google app is disconnected in the vault. An operator config fault, not a retry.
- **`unavailable at this tier` / `access_restricted` (Google 403)** — this tier has no Google reach (untrusted is gated by design). Report the claim as unverified; do not reach for another route.

Any other non-zero exit (network, timeout, bad stdin, unknown op) is likewise reported, not retried here. Finish here.
