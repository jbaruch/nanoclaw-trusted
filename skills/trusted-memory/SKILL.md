---
name: trusted-memory
description: Session bootstrap and rolling memory updates for trusted containers. On session start, reads MEMORY.md (permanent facts), RUNBOOK.md (operational workflows), recent daily and weekly logs, and highlights.md to restore context. After non-trivial interactions, appends timestamped entries to group-local and cross-group shared daily logs. Use when starting a new session to load previous notes and remember context, or after meaningful conversations to save conversation history, persist session state, or record newly learned owner preferences.
---

# Trusted Memory

This skill is an action router — pick the step that matches the user's intent and execute only that step. Do not run other steps; do not parallelize. Step 1 and Step 3 each chain to Step 4 where they say so.

This skill applies to trusted and main containers only. `/workspace/trusted/` is mounted there; untrusted containers do not have the mount.

Store layout, typed-file frontmatter and naming, the `MEMORY.md` index shape, size limits, and the nightly archival pipeline are reference material, not steps:

```text
skills/trusted-memory/references/memory-store.md
```

On-disk state shapes — `session-state.json` and the canonical `## Addresses` block — are in `skills/trusted-memory/state-schema.md`.

## Step 1 — Bootstrap the Session

The agent-runner's `session-start-auto-context` hook already injects MEMORY.md, RUNBOOK.md, and the most-recent daily log. Read them anyway when a step below names them; this step also covers what the hook does not — group-shared `trusted/` memory, weekly logs, `highlights.md` — plus the per-session sentinel and state stamping.

First, check if bootstrap is needed. The sentinel is keyed to the current session ID, so a new session in the same container still triggers bootstrap:

```
python3 /home/node/.claude/skills/tessl__trusted-memory/scripts/needs-bootstrap.py
```

Exit 0 = bootstrap IS needed, exit 1 = skip bootstrap (sentinel matches current session). From Python: `subprocess.run([...]).returncode == 0`. From Bash: branch on `$?`. Also emits a single-line JSON status to stdout (`{"needs_bootstrap": <bool>, "current": ..., "stored": ..., "reason": ...}`) for callers that want to log the decision.

If bootstrap is NOT needed → finish here, silent.

If bootstrap IS needed → run these reads in order:

1. Read `/workspace/trusted/MEMORY.md` — lightweight index. Scan entries and load the 2-3 most relevant typed files based on current context.
2. Read `/workspace/trusted/RUNBOOK.md` — operational workflows and tool knowledge.
3. Read the most recent 2 files from `/workspace/group/memory/daily/` in full (yesterday + today).
4. Read the most recent 2 files from `/workspace/group/memory/weekly/` as summaries (older context).
5. Read the most recent 2 files from `/workspace/trusted/memory/daily/` (cross-group shared memory).
6. Read `/workspace/trusted/highlights.md` if it exists (major long-term events).
7. Write session metadata into `session-state.json` under a per-session subtree. See `state-schema.md` for the on-disk shape and the legacy back-compat field. Current-session stamping:

```
python3 /home/node/.claude/skills/tessl__trusted-memory/scripts/register-session.py
```

One invocation writes both the session-state entry and the bootstrap sentinel — inputs, environment variables, and write behaviour are in the script's docstring; the on-disk shapes are in `state-schema.md`. Emits single-line JSON `{"session_id", "session_name", "schema_version", "wrote_state", "wrote_sentinel"}`.

Flow-relevant: a run that writes the state but not the sentinel re-bootstraps next session. That is safe — the reads above are idempotent — so treat a `wrote_sentinel: false` as noted, not as a failure to retry.

Total context budget for memory: ~3000 tokens. Summarize large files before loading.

**Error handling.**

- **Missing files**: Skip silently and continue. Do not treat absence as an error.
- **Missing `session-state.json`**: Treat as a fresh session — proceed through all the reads; read 7 creates the file.
- **Corrupt or unreadable `session-state.json`**: Treat as missing — overwrite with the current session ID after completing bootstrap.
- **Missing or empty daily/weekly directories**: Skip those reads and proceed. Note in the first rolling memory update that this is a new memory store.

Bootstrap reads the owner profile, so proceed to Step 4 — the owner migrates its `## Addresses` block on read, never on some later edit. Finish after Step 4.

## Step 2 — Record a Rolling Memory Update

After any non-trivial interaction (decision made, action taken, something new learned about the owner's preferences):

**Group-local log** — pipe the bullet line into `append-to-daily-log.py --target group`:

```bash
echo "- HH:MM UTC — [what happened / what was learned]" \
  | python3 /home/node/.claude/skills/tessl__trusted-memory/scripts/append-to-daily-log.py \
      --target group
```

**Cross-group shared log** — same helper with `--target trusted` and a `[chat-name]` source-attribution prefix:

```bash
echo "- HH:MM UTC [chat-name] — [what happened / what was learned]" \
  | python3 /home/node/.claude/skills/tessl__trusted-memory/scripts/append-to-daily-log.py \
      --target trusted
```

Where `[chat-name]` is derived from the group folder name (e.g. `main`, `swarm`, `dedy-bukhtyat`). Multiple bullets in one call: pass repeated `--line "..."` flags or pipe a newline-delimited block on stdin.

The helper resolves the target file, serialises concurrent writers, and creates the daily file on first call — date resolution, locking, dedup predicate, and write mechanics are in `skills/trusted-memory/scripts/append-to-daily-log.py`. Override the daily-dir for non-canonical mount layouts with `--group-daily` / `--trusted-daily`, or the matching `NANOCLAW_GROUP_DAILY` / `NANOCLAW_TRUSTED_DAILY` env vars.

Stdout: `{"path", "appended_lines", "dropped_duplicates", "final_line_count", "created", "out_of_order"}`. Duplicate lines are dropped rather than appended, so an all-duplicates call is a valid no-op — read `appended_lines`, not exit status, to know whether anything landed. A stderr out-of-order warning accompanies `out_of_order: true`; the lines still land, so it is a note, not a failure.

Skip for pure heartbeats with nothing to report or trivial acknowledgements. Finish here.

## Step 3 — Save a Permanent Fact

When learning something that should persist (owner preference, architecture decision, new contact, external system reference):

1. Create or update the appropriate typed file in `/workspace/trusted/`
2. Add or update its one-line entry in `/workspace/trusted/MEMORY.md`
3. Also append to today's daily log (so archival can track when it was learned)

Do NOT wait for nightly archival to create typed files — save immediately.

Editing `user_profile.md` rewrites the file carrying the canonical `## Addresses` block, so proceed to Step 4 and finish there. Preserve the block's `- <key>: <value>` line shape while editing — the travel tile parses it. Any other typed file finishes here.

## Step 4 — Migrate the Addresses Block

Run the owner-side migration of `user_profile.md`'s canonical `## Addresses` block. Reached from Step 1 (the owner migrates on read, per `jbaruch/coding-policy: stateful-artifacts`) and from Step 3 after writing `user_profile.md`.

```
python3 /home/node/.claude/skills/tessl__trusted-memory/scripts/migrate-addresses-block.py
```

Idempotent: a block already at the current version is left byte-identical. Emits single-line JSON `{"migrated": <bool>, "from": <int|null>, "to": <int>, "path": "..."}`; exit 1 with an actionable stderr diagnostic when the profile is missing/unreadable, carries no block, or carries a stamp the script refuses to rewrite. The version constant, what gets restamped, and what is deliberately NOT added live in the script and `state-schema.md` — do not restate or re-derive them here, and never hand-edit the block's stamp.

On a non-zero exit, report the diagnostic verbatim and stop; the block is unchanged on disk. Finish here.
