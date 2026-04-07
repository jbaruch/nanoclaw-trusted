## Verification Protocol

After these actions, verify independently before confirming to the user:

- **File writes**: Read the file back. Compare key content against what you intended to write.
- **Task scheduling**: Read `current_tasks.json`. Confirm the task appears with the correct schedule.
- **API calls via Composio**: Check the response status AND the response body. A 200 doesn't mean the data is correct.
- **Memory updates**: Read the memory file back after writing. Confirm the content matches.
- **IPC messages**: After writing to `/workspace/ipc/messages/`, verify the file exists and contains the expected payload.

The tool call returning success is NOT verification. The tool call succeeding means the tool ran — not that the outcome is what you intended. Read it back.
