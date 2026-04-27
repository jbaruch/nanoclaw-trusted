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

**project** — Ongoing work with absolute dates. Example:
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

First, check if bootstrap is needed. The sentinel is keyed to the current session ID so a new session within the same container still triggers bootstrap:

```python
import os
sentinel = '/tmp/session_bootstrapped'
current_session = os.environ.get('CLAUDE_SESSION_ID', '')
needs_bootstrap = True
if os.path.exists(sentinel):
    stored = open(sentinel).read().strip()
    needs_bootstrap = (stored != current_session)
```

If `needs_bootstrap` is **False** → skip bootstrap entirely. Silent.

If `needs_bootstrap` is **True** → run all steps below in order:

1. Read `/workspace/trusted/MEMORY.md` — lightweight index. Scan entries and load the 2-3 most relevant typed files based on current context.
2. Read `/workspace/trusted/RUNBOOK.md` — operational workflows and tool knowledge.
3. Read the most recent 2 files from `/workspace/group/memory/daily/` in full (yesterday + today).
4. Read the most recent 2 files from `/workspace/group/memory/weekly/` as summaries (older context).
5. Read the most recent 2 files from `/workspace/trusted/memory/daily/` (cross-group shared memory).
6. Read `/workspace/trusted/highlights.md` if it exists (major long-term events).
7. Write the current `session_id` to `/workspace/group/session-state.json` via the helper script:

```bash
python3 /home/node/.claude/skills/tessl__trusted-memory/scripts/sync-session-id.py
```

The script reads `session_id` from the messages DB, takes `fcntl.LOCK_EX` on `/workspace/group/session-state.json.lock` (the §8 registry convention for this multi-writer file), atomic-writes the JSON (tempfile → flush → fsync → mode-preserve → `os.replace` → read-back verify) only when the value actually changes, and prints a single-line JSON status to stdout: `{"session_id": "<id-or-null>", "wrote": <bool>}` — `wrote=true` means the file was rewritten this call, `wrote=false` means the cached value was already current. Exits 0 on success / 1 on any DB / lock / write failure with a `sync-session-id:`-prefixed diagnostic on stderr / 2 on usage error (extra argv). On exit 1 the caller MUST stop bootstrap — the downstream sentinel write would otherwise persist a stale session id.

8. Write the sentinel with current session ID: `open('/tmp/session_bootstrapped', 'w').write(current_session)`

Total context budget for memory: ~3000 tokens. Summarize large files before loading.

### Bootstrap Error Handling

- **Missing files**: Skip silently and continue. Do not treat absence as an error.
- **Missing `session-state.json`**: Treat as a fresh session — proceed through all steps and create the file at step 7.
- **Corrupt or unreadable `session-state.json`**: Treat as missing — overwrite with the current session ID after completing bootstrap.
- **Missing or empty daily/weekly directories**: Skip those steps and proceed. Note in the first rolling memory update that this is a new memory store.

## Rolling Memory Updates

After any non-trivial interaction (decision made, action taken, something new learned about the owner's preferences):

**Group-local log** — append to `/workspace/group/memory/daily/YYYY-MM-DD.md`:
```
- HH:MM UTC — [what happened / what was learned]
```

**Cross-group shared log** — also append to `/workspace/trusted/memory/daily/YYYY-MM-DD.md` with source attribution:
```
- HH:MM UTC [chat-name] — [what happened / what was learned]
```
Where `[chat-name]` is derived from the group folder name (e.g. `main`, `swarm`, `dedy-bukhtyat`).

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
