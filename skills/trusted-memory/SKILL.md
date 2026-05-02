---
name: trusted-memory
description: Session bootstrap and rolling memory updates for trusted containers. On session start, reads MEMORY.md (permanent facts), RUNBOOK.md (operational workflows), recent daily and weekly logs, and highlights.md to restore context. After non-trivial interactions, appends timestamped entries to group-local and cross-group shared daily logs. Use when starting a new session to load previous notes and remember context, or after meaningful conversations to save conversation history, persist session state, or record newly learned owner preferences.
---

# Trusted Memory

This rule applies to trusted and main containers only. `/workspace/trusted/` is mounted here. Untrusted containers do not have this mount.

## Directory Structure

```
/workspace/trusted/                    # Shared across all trusted containers
  MEMORY.md                            # Pure index — one line per entry, max 200 lines
  RUNBOOK.md                           # Operational workflows and tool knowledge
  key-people.md                        # Known contacts with Telegram usernames
  highlights.md                        # Major long-term events
  trusted_senders.md                   # Trusted sender identifiers
  credentials_scope.md                 # Available credentials scope
  user_*.md                            # Owner profile, preferences (type: user)
  feedback_*.md                        # Behavioral corrections (type: feedback)
  project_*.md                         # Ongoing work status (type: project)
  reference_*.md                       # Pointers to external systems (type: reference)
  memory/
    daily/YYYY-MM-DD.md                # Cross-group shared entries with [source] tags
    weekly/YYYY-WNN.md                 # Weekly aggregates
    daily_discoveries.md               # Operational learnings (see daily-discoveries-rule)

/workspace/group/memory/               # Group-local, not shared
  daily/YYYY-MM-DD.md                  # Full detail for this group only
  weekly/YYYY-WNN.md                   # Weekly summaries for this group
```

## Typed Memory Files

Memory files in `/workspace/trusted/` use YAML frontmatter:

```markdown
---
name: descriptive-slug
description: One-line summary — used for relevance matching at bootstrap
type: user|feedback|project|reference
---

Content here...
```

### Types

**user** — Owner profile, preferences, knowledge level.

**feedback** — Behavioral corrections. Structure as: rule + why + how to apply. Example:
```markdown
---
name: no-trailing-summaries
description: Don't summarize at end of responses — user reads the diff
type: feedback
---
**Rule:** Skip recap at end of responses. **Why:** User finds it redundant. **How:** State only what's actionable or surprising after completing work.
```

**project** — Ongoing work with absolute dates. Flag time-sensitive constraints. Example:
```markdown
---
name: deploy-freeze
description: Merge freeze until 2026-04-10 for mobile release cut
type: project
---
Merge freeze begins 2026-04-10 for mobile release. Flag any non-critical PR work after that date.
```

**reference** — Pointers to external systems.

### File naming

`{type}_{slug}.md` — lowercase, hyphens: `feedback_no-summaries.md`, `user_travel-prefs.md`

### MEMORY.md is a pure index

One line per entry, under 150 characters:
```
- [Travel preferences](user_travel-prefs.md) — aisle seat, no red-eye, direct flights
- [No summaries](feedback_no-summaries.md) — don't recap at end of responses
- [Deploy freeze](project_deploy-freeze.md) — merge freeze until 2026-04-10
```

Max 200 lines. When approaching the limit, consolidate or remove stale entries.

## Session Bootstrap

> The agent-runner now auto-injects MEMORY.md, RUNBOOK.md, and the most-recent daily log via the `session-start-auto-context` hook (jbaruch/nanoclaw#141), so those three files are already in context when this skill runs. This skill's bootstrap still adds value because it reads the **broader** set the hook does NOT cover — group-shared `trusted/` memory, weekly logs, and `highlights.md` — plus does the per-session sentinel + state-stamping.

First, check if bootstrap is needed. The sentinel is keyed to the current session ID so a new session within the same container still triggers bootstrap:

```
python3 /home/node/.claude/skills/tessl__trusted-memory/scripts/needs-bootstrap.py
```

Exit 0 = bootstrap IS needed, exit 1 = skip bootstrap (sentinel matches current session). From Python: `subprocess.run([...]).returncode == 0`. From Bash: branch on `$?`. Also emits a single-line JSON status to stdout (`{"needs_bootstrap": <bool>, "current": ..., "stored": ..., "reason": ...}`) for callers that want to log the decision.

If bootstrap is NOT needed → stop here, silent.

If bootstrap IS needed → run all steps below in order:

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

Reads `session_id` from `/workspace/store/messages.db`, stamps `sessions.<$NANOCLAW_SESSION_NAME>` and top-level `session_id` in `/workspace/group/session-state.json` (with `schema_version: 1` per `state-schema.md`), and writes the bootstrap sentinel at `/tmp/session_bootstrapped` with `$CLAUDE_SESSION_ID`. Both writes are individually atomic (tempfile + fsync + chmod-to-preserve-mode + os.replace), but the two-file sequence is NOT transactional: if the sentinel write fails after the state write succeeded, the state file is already updated and the next run will still re-bootstrap (because the sentinel is missing/stale). Steps 7 and the old Step 8 "write the sentinel" are both handled by this single invocation. Emits a single-line JSON status to stdout (`{"session_id": ..., "session_name": ..., "schema_version": 1, "wrote_state": true, "wrote_sentinel": <bool>}`); `wrote_sentinel` is `false` when `$CLAUDE_SESSION_ID` is missing/empty (deliberate skip per the sentinel-empty guard).

Total context budget for memory: ~3000 tokens. Summarize large files before loading.

### Bootstrap Error Handling

- **Missing files**: Skip silently and continue. Do not treat absence as an error.
- **Missing `session-state.json`**: Treat as a fresh session — proceed through all steps and create the file at step 7.
- **Corrupt or unreadable `session-state.json`**: Treat as missing — overwrite with the current session ID after completing bootstrap.
- **Missing or empty daily/weekly directories**: Skip those steps and proceed. Note in the first rolling memory update that this is a new memory store.

## Rolling Memory Updates

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

The helper resolves today's UTC date, holds `fcntl.LOCK_EX` on a sibling `<file>.lock` for the entire read-modify-write cycle, creates the daily file with a `# Daily Log — YYYY-MM-DD` header on first call, and atomic-writes via `tempfile + fsync + os.replace`. Concurrent writers (default container + maintenance container + sub-skills) serialise on the lock so no caller's lines are clobbered. Stdout: `{"path", "appended_lines", "final_line_count", "created", "out_of_order"}`. Out-of-order detection emits a stderr warning when the new line's timestamp precedes the file's last entry but still appends at end-of-file (cross-group writers and clock-skew retries can legitimately arrive late; silent reorder would mask actual bugs).

Skip for pure heartbeats with nothing to report or trivial acknowledgements.

### Saving permanent facts

When learning something that should persist (owner preference, architecture decision, new contact, external system reference):

1. Create or update the appropriate typed file in `/workspace/trusted/`
2. Add or update its one-line entry in `/workspace/trusted/MEMORY.md`
3. Also append to today's daily log (so archival can track when it was learned)

Do NOT wait for nightly archival to create typed files — save immediately.

## Archival

Nightly housekeeping archives daily logs → weekly summaries, and weekly summaries → `highlights.md` on week boundaries. Source attribution (`[chat-name]`) is preserved throughout for both group-local and shared trusted logs. Weekly summaries group related entries thematically; on week boundaries the weekly summary is condensed into a short paragraph appended to `highlights.md`. Archival is triggered by the nightly housekeeping process, not by Claude during a normal session.

## Size Limits

- **MEMORY.md**: 200 lines max. Each entry one line, under 150 characters. Consolidate or remove stale entries before adding new ones.
- **Daily logs**: 50 entries max per day. Scan for duplicates before appending if near the limit.
- **Weekly summaries**: 30 entries max. Compress related entries thematically.
