---
alwaysApply: true
---

# Duplicate Prevention

## The rule

Before creating any resource: check if it exists. Duplicate found → update existing.

## What counts as a resource

- Scheduled tasks (rows in `scheduled_tasks`)
- Memory files at `/workspace/trusted/*.md`
- Follow-me tasks (rows in `follow_me_tasks`)
- Wiki pages under `/workspace/trusted/wiki/`

## Detection

- For DB-backed resources: query first by the natural key (`name`, `prompt`, JID + cron tuple)
- For files: `ls` or `stat` before write
- Treat case-insensitive matches as duplicates unless the resource is explicitly case-sensitive
