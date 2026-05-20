---
alwaysApply: true
---

# Skills Policy

## Invoke via Skill tool

If a skill exists, invoke it with `Skill(skill: "name")`. Skills in `.claude/skills/` are discovered automatically.

## Don't paste SKILL.md content

Never read SKILL.md files manually or paste their content into Agent prompts. The Skill tool is the only correct entry point.

## Background skills

Spawn `Agent` with `run_in_background: true` and instruct it to invoke the skill via the `Skill` tool inside the sub-agent.

## No improvising

The skill has a defined process. Follow it. Don't paraphrase steps, don't reorder steps, don't skip steps.
