# Memory Store Reference

Layout, file conventions, and limits for the trusted memory store. Read this when a step needs the shape of a file it is about to write; the steps themselves live in `SKILL.md`.

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

**user** — Owner profile, preferences, knowledge level. `user_profile.md` is a canonical, **special-case** file with a fixed name (it does NOT follow the general `user_<slug>.md` / `{type}_{slug}.md` pattern below). It additionally carries the canonical machine-readable `## Addresses` block (`current_home` / `home_airport` / `home_metro` / `new_home_wip`) read by the travel tile — schema and reader contract in `state-schema.md`. This skill owns that block; Step 4 of `SKILL.md` migrates it.

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

## Archival

Nightly housekeeping archives daily logs → weekly summaries, and weekly summaries → `highlights.md` on week boundaries. Source attribution (`[chat-name]`) is preserved throughout for both group-local and shared trusted logs. Weekly summaries group related entries thematically; on week boundaries the weekly summary is condensed into a short paragraph appended to `highlights.md`. Archival is triggered by the nightly housekeeping process, not by Claude during a normal session.

## Size Limits

- **MEMORY.md**: 200 lines max. Each entry one line, under 150 characters. Consolidate or remove stale entries before adding new ones.
- **Daily logs**: 50 entries max per day. Scan for duplicates before appending if near the limit.
- **Weekly summaries**: 30 entries max. Compress related entries thematically.
