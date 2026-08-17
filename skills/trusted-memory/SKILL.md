---
name: trusted-memory
description: Session bootstrap and rolling memory updates for trusted containers. On session start, reads MEMORY.md (permanent facts), RUNBOOK.md (operational workflows), recent daily and weekly logs, and highlights.md to restore context. After non-trivial interactions, appends timestamped entries to group-local and cross-group shared daily logs. Use when starting a new session to load previous notes and remember context, or after meaningful conversations to save conversation history, persist session state, or record newly learned owner preferences.
---

# Trusted Memory

This skill is an action router — pick the step that matches the user's intent and execute only that step. Do not run other steps; do not parallelize. Step 1 and Step 3 each chain to Step 4 where they say so.

This skill applies to trusted and main containers only. `/workspace/trusted/` is mounted there; untrusted containers do not have the mount.

Store layout, typed-file frontmatter and naming, the `MEMORY.md` index shape, size limits, and the nightly archival pipeline are reference material, not steps:

```
skills/trusted-memory/references/memory-store.md
```

On-disk state shapes — `session-state.json` and the canonical `## Addresses` block — are in `skills/trusted-memory/state-schema.md`.

## Step 1 — Bootstrap the Session

> The agent-runner now auto-injects MEMORY.md, RUNBOOK.md, and the most-recent daily log via the `session-start-auto-context` hook (jbaruch/nanoclaw#141), so those three files are already in context when this skill runs. This skill's bootstrap still adds value because it reads the **broader** set the hook does NOT cover — group-shared `trusted/` memory, weekly logs, and `highlights.md` — plus does the per-session sentinel + state-stamping.

First, check if bootstrap is needed. The sentinel is keyed to the current session ID so a new session within the same container still triggers bootstrap:

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

Reads `session_id` from `/workspace/store/messages.db`, stamps `sessions.<$NANOCLAW_SESSION_NAME>` and top-level `session_id` in `/workspace/group/session-state.json` (with `schema_version: 1` per `state-schema.md`), and writes the bootstrap sentinel at `/tmp/session_bootstrapped` with `$CLAUDE_SESSION_ID`. Both writes are individually atomic (tempfile + fsync + chmod-to-preserve-mode + os.replace), but the two-file sequence is NOT transactional: if the sentinel write fails after the state write succeeded, the state file is already updated and the next run will still re-bootstrap (because the sentinel is missing/stale). Read 7 and the old "write the sentinel" read are both handled by this single invocation. Emits a single-line JSON status to stdout (`{"session_id": ..., "session_name": ..., "schema_version": 1, "wrote_state": true, "wrote_sentinel": <bool>}`); `wrote_sentinel` is `false` when `$CLAUDE_SESSION_ID` is missing/empty (deliberate skip per the sentinel-empty guard).

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

The helper resolves today's UTC date, holds `fcntl.LOCK_EX` on a sibling `<file>.lock` for the entire read-modify-write cycle, creates the daily file with a `# Daily Summary — YYYY-MM-DD` header on first call (the canonical header the nightly archive pipeline recognises), and atomic-writes via `tempfile + fsync + os.replace`. Concurrent writers (default container + maintenance container + sub-skills) serialise on the lock so no caller's lines are clobbered. Override the daily-dir for non-canonical mount layouts via `--group-daily` / `--trusted-daily` flags or `NANOCLAW_GROUP_DAILY` / `NANOCLAW_TRUSTED_DAILY` env vars (flag wins over env). Stdout: `{"path", "appended_lines", "dropped_duplicates", "final_line_count", "created", "out_of_order"}`. Out-of-order detection emits a stderr warning when the new line's timestamp precedes the file's last entry but still appends at end-of-file (cross-group writers and clock-skew retries can legitimately arrive late; silent reorder would mask actual bugs).

Per `jbaruch/nanoclaw#365`: candidate lines whose whitespace-normalized form already appears in the file (or duplicates an earlier line in the same batch) are skipped at write time and counted in `dropped_duplicates`. All-duplicates is a valid no-op — the file's mtime and inode stay untouched. Existing on-disk lines are never rewritten; dedup only affects new appends.

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

Idempotent — a block already at the current version is left byte-identical, so running it every session is free. Emits single-line JSON `{"migrated": <bool>, "from": <int|null>, "to": <int>, "path": "..."}`; exit 1 with an actionable stderr diagnostic when the profile is missing/unreadable, carries no block, or carries a stamp the script refuses to rewrite. The version constant, what gets restamped, and what is deliberately NOT added live in the script and `state-schema.md` — do not restate or re-derive them here, and never hand-edit the block's stamp.

On a non-zero exit, report the diagnostic verbatim and stop; the block is unchanged on disk. Finish here.
