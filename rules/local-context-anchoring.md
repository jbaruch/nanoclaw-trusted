---
alwaysApply: true
---

# Local-context anchoring

Before answering, anchor to the user's local frame. The orchestrator injects this in the `<context>` tag at the start of each agent invocation:

- `local_datetime`, `local_date`, `weekday` — the user's local clock and calendar.
- `timezone` (+ `timezone_source` showing how it was resolved).
- `location_lat`, `location_lng`, `location_age_minutes` — current physical position when a recent shared location exists.

## Anchor relative phrasings to the local frame

All relative phrasings — `today`, `yesterday`, `tomorrow`, `now`, `сегодня`, `вчера`, `завтра`, `сейчас`, `here`, `where`, etc. — refer to **the user's local frame**, not the server clock and not UTC.

When the calendar / email / scheduled-task data carries UTC or another zone, convert before phrasing. Examples:

- Event `2026-05-15T17:00:00+02:00` while `<context>` says `local_date="2026-05-16"` → call it "yesterday", never "сегодня".
- Reminder `next_run="2026-05-17T05:00:00Z"` while `<context>` says `weekday="Saturday"` → "tomorrow morning your local", not "Sunday at 5 UTC".

## Surface uncertainty when the anchor is weak

When `timezone_source="container_default"` (no location pin AND no itinerary-derived timezone was available, so the orchestrator fell back to the container's `TZ` env), say so — the answer's date frame may be wrong, and the user should know to correct.

Don't pretend to know `here` if `location_*` attrs are absent — the `<context>` tag only emits `location_lat` / `location_lng` / `location_age_minutes` when `timezone_source="location"` (a fresh shared-location pin drove the resolution). When `timezone_source` is anything other than `location` (currently `segment` / `home_fallback` / `container_default` in this orchestrator version) the agent has no physical-position signal and `here` is unknown.

## Trumps inline data formats

This rule is universal. If the agent text uses a relative-time word, the local frame controls — regardless of how the source data is shaped.
