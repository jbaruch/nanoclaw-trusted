---
alwaysApply: true
---

# Skills Policy

If a skill exists, invoke it with `Skill(skill: "name")`. Skills in `.claude/skills/` are discovered automatically — do NOT read SKILL.md files manually or paste content into Agent prompts.

## Background skills

Spawn `Agent` with `run_in_background: true`. Instruct it to invoke the skill via the `Skill` tool.

## No improvising

The skill has a defined process. Follow it.
