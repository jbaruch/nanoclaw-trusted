---
alwaysApply: true
---

# Context Bootstrap for Background Agents

When launching a background `Agent`, include workspace context in the prompt:

```
Workspace: /workspace/group/ (your files), /workspace/ipc/ (messaging).
Send results via mcp__nanoclaw__send_message.
Telegram HTML: <b>bold</b>, <i>italic</i>, • bullets. No markdown.
```
