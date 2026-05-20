---
alwaysApply: true
---

# Context Bootstrap for Background Agents

When launching a background `Agent`, prepend the prompt with these workspace-context lines.

## Required preamble lines

- `Workspace: /workspace/group/ (your files), /workspace/ipc/ (messaging).`
- `Send results via mcp__nanoclaw__send_message.`
- `Telegram HTML: <b>bold</b>, <i>italic</i>, • bullets. No markdown.`

## When to omit

If the parent prompt already includes equivalent context (e.g., a Skill that injects it), don't duplicate the preamble. Duplication confuses the sub-agent about which copy is authoritative.

## Tools available to sub-agents

- `mcp__nanoclaw__send_message` — outbound IPC to chat
- `mcp__nanoclaw__react_to_message` — reaction on the originating message
- The full `Skill()` tool surface — sub-agents can invoke any installed skill
