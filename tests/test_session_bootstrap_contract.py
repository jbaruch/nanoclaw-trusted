"""Prompt routing contracts; no live model or scheduled-skill evals."""

from .conftest import REPO_ROOT


def test_scheduled_task_skill_runs_before_registration():
    rule = (REPO_ROOT / "rules/session-bootstrap.md").read_text()

    assert "[SCHEDULED TASK -" in rule
    assert "first tool call is the task skill, with no bootstrap reads" in rule
    assert (
        'After the task skill, invoke `Skill(skill: "tessl__trusted-memory")` '
        "Step 1 for registration only."
    ) in rule
    assert rule.index("first tool call") < rule.index('Skill(skill: "tessl__trusted-memory")')


def test_scheduled_step_one_skips_reads_but_registers_once():
    skill = (REPO_ROOT / "skills/trusted-memory/SKILL.md").read_text()
    bootstrap = skill.split("## Step 1 — Bootstrap the Session\n", 1)[1].split("## Step 2", 1)[0]
    scheduled_guard = bootstrap.split("The agent-runner", 1)[0]

    assert "[SCHEDULED TASK -" in scheduled_guard
    assert "skip the sentinel check and reads 1–6" in scheduled_guard
    assert "Run only session registration in item 7" in scheduled_guard
    assert "finish here, silent" in scheduled_guard
    assert "do not proceed to Step 4" in scheduled_guard
    assert "own steps" in scheduled_guard
    assert bootstrap.count("scripts/register-session.py\n") == 1
    assert "Steps 2 and 3" in scheduled_guard


def test_interactive_bootstrap_keeps_sentinel_reads_registration_and_migration():
    rule = (REPO_ROOT / "rules/session-bootstrap.md").read_text()
    skill = (REPO_ROOT / "skills/trusted-memory/SKILL.md").read_text()
    bootstrap = skill.split("## Step 1 — Bootstrap the Session\n", 1)[1].split("## Step 2", 1)[0]

    assert 'Skill(skill: "tessl__trusted-memory")' in rule
    assert "re-bootstrap on a missing or mismatched sentinel; skip on a match." in rule.lower()
    assert "scripts/needs-bootstrap.py\n" in bootstrap
    assert "If bootstrap is NOT needed → finish here, silent." in bootstrap
    assert "If bootstrap IS needed → run these reads in order:" in bootstrap
    reads = (
        "1. Read `/workspace/trusted/MEMORY.md`",
        "2. Read `/workspace/trusted/RUNBOOK.md`",
        "3. Read the most recent 2 files from `/workspace/group/memory/daily/` in full",
        "4. Read the most recent 2 files from `/workspace/group/memory/weekly/` as summaries",
        "5. Read the most recent 2 files from `/workspace/trusted/memory/daily/`",
        "6. Read `/workspace/trusted/highlights.md` if it exists",
        "7. Write session metadata",
    )
    positions = [bootstrap.index(read) for read in reads]
    assert positions == sorted(positions)
    assert "scripts/register-session.py\n" in bootstrap
    assert "proceed to Step 4" in bootstrap.split("**Error handling.**", 1)[1]
    for failure in (
        "**Missing files**: Skip silently and continue.",
        "**Missing `session-state.json`**: Treat as a fresh session",
        "**Corrupt or unreadable `session-state.json`**: Treat as missing",
        "**Missing or empty daily/weekly directories**: Skip those reads and proceed.",
    ):
        assert failure in bootstrap
