---
alwaysApply: true
---

# Composio vs Agents

## Direct Composio call

Use a direct Composio tool invocation when:

- The task is a single API call
- The operation is a read or simple data fetch
- The result is the answer (no further reasoning needed)

## Spawned Agent

Spawn an `Agent` when:

- The task takes multi-step workflow
- Judgment is required across multiple tool calls
- The control flow branches based on intermediate results

## Rule of thumb

One tool call with a clear answer → Composio. Think between steps → Agent.
