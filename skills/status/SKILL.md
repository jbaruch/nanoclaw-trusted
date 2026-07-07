---
name: status
description: Quick read-only health check — session context, workspace mounts, tool availability, and task snapshot. Use when the user asks for system status, health check, diagnostics, system info, check environment, what tools are available, or runs /status.
---

# /status — System Status Check

Process steps in order. Do not skip ahead.

Generate a quick read-only status report of the current agent environment.

**Trusted/main scope.** This skill ships in the trusted tile, so it is only mounted in trusted and main containers — the workspace/mount/IPC details it reports never surface in untrusted groups (`jbaruch/nanoclaw-core#68`).

## Step 1 — Capture session context

```bash
echo "Timestamp: $(date)"
echo "Working dir: $(pwd)"
echo "Chat: ${NANOCLAW_CHAT_JID:-unknown}"
```

The chat scope comes from `NANOCLAW_CHAT_JID`, set automatically inside every container — do not assert a channel name the environment doesn't confirm. Proceed immediately to Step 2.

## Step 2 — Compute container uptime

Run the `container-uptime.py` script (`scripts/container-uptime.py` relative to this skill, mounted into the agent at `/home/node/.claude/skills/tessl__status/scripts/container-uptime.py` — the absolute path matches every other `tessl__*` skill in this tile and is what the agent must literally invoke):

```bash
python3 /home/node/.claude/skills/tessl__status/scripts/container-uptime.py | python3 -c 'import json,sys; print(json.load(sys.stdin)["uptime_text"])'
```

The script outputs single-line JSON `{"uptime_text": "<Nd Hh (since ISO8601)>", "started": "<ISO8601>"}`. The pipe extracts `uptime_text` for direct rendering. On a non-container host (no `/.dockerenv`), `uptime_text` is `"unknown"` and `started` is `null`. Reads `/.dockerenv` mtime, which Docker creates at container spawn time — present in every container, no external state file needed. Proceed immediately to Step 3.

## Step 3 — List workspace and mount visibility

```bash
echo "=== Workspace ==="
ls /workspace/ 2>/dev/null
echo "=== Group folder ==="
ls /workspace/group/ 2>/dev/null | head -20
echo "=== Extra mounts ==="
ls /workspace/extra/ 2>/dev/null || echo "none"
echo "=== IPC ==="
ls /workspace/ipc/ 2>/dev/null
```

Proceed immediately to Step 4.

## Step 4 — Probe tool availability

```bash
which agent-browser 2>/dev/null && echo "Web (agent-browser): available" || echo "Web (agent-browser): unavailable"
ls /workspace/ipc/ 2>/dev/null && echo "Orchestration (IPC): available" || echo "Orchestration (IPC): unavailable"
node --version 2>/dev/null
claude --version 2>/dev/null
```

Then call `mcp__nanoclaw__list_tasks` — if it succeeds, report **MCP: available** and keep the result for Step 5; if it errors, report **MCP: unavailable**. Proceed immediately to Step 5.

## Step 5 — Snapshot scheduled tasks

Use the result from `mcp__nanoclaw__list_tasks`. If no tasks exist, report "No scheduled tasks." Proceed immediately to Step 6.

## Step 6 — Render the report

Present using Telegram HTML, adapting each section to what you actually found:

```
🔍 <b>NanoClaw Status</b>

<b>Session:</b>
• Chat: <NANOCLAW_CHAT_JID value / group name>
• Time: 2026-03-14 09:30 UTC
• Working dir: /workspace/group

<b>Container:</b>
• Uptime: Nd Hh (started YYYY-MM-DDTHH:MM:SSZ)
• agent-browser: ✓ / not installed
• Node: vXX.X.X
• Claude Code: vX.X.X

<b>Workspace:</b>
• Group folder: ✓ (N files)
• Extra mounts: none / N directories
• IPC: ✓ (messages, tasks, input)

<b>Tools:</b>
• Core: ✓  Web: ✓  Orchestration: ✓  MCP: ✓

<b>Scheduled Tasks:</b>
• N active tasks / No scheduled tasks
```

Keep it concise — this is a quick health check, not a deep diagnostic.

**See also:** `/capabilities` for a full list of installed skills and tools.

Finish here.
