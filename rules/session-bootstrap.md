---
alwaysApply: true
---

# Session Bootstrap — MANDATORY First Action

**YOUR VERY FIRST ACTION in every new session — before responding to ANY message — is to run this Bash command:**

```bash
cat /tmp/session_bootstrapped 2>/dev/null
```

**If the file is missing or empty** → run: `Skill(skill: "tessl__trusted-memory")`

Then write the sentinel: `echo "done" > /tmp/session_bootstrapped`

**If the file exists and contains "done"** → bootstrap already ran this session, skip.

This is not optional. This is not background context. This is Step 0 of every session. If you respond to a user message without checking this first, you are violating this rule.
