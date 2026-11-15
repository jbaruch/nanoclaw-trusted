"""Baseline tests for skills/trusted-memory/scripts/register-session.py.

Covers the documented contract:
  - Reads session_id from /workspace/store/messages.db (sqlite3); tolerates
    sqlite errors as session_id=None rather than crashing.
  - Atomically writes session-state.json (sessions.<name> + back-compat
    top-level session_id + schema_version).
  - Atomically writes /tmp/session_bootstrapped sentinel — UNLESS
    --registration-only is passed or both session identity variables are
    empty. Registration alone leaves any existing sentinel untouched.
  - Emits a single-line JSON status to stdout per script-delegation rule.
"""

import json
import shlex
import sqlite3
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from .conftest import REPO_ROOT, load_script

SCRIPT_REL = "skills/trusted-memory/scripts/register-session.py"


def _make_messages_db(path, session_id):
    """Production shape of `sessions` per `rules/messages-db-schema.md`
    (verified against the live host DB): keyed by
    (`group_folder`, `session_name`), one row per group session."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE sessions ("
        "  group_folder TEXT NOT NULL,"
        "  session_name TEXT NOT NULL DEFAULT 'default',"
        "  session_id TEXT NOT NULL,"
        "  PRIMARY KEY (group_folder, session_name)"
        ")"
    )
    if session_id is not None:
        conn.execute(
            "INSERT INTO sessions (group_folder, session_name, session_id) "
            "VALUES ('telegram_swarm', 'default', ?)",
            (session_id,),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def register_session(tmp_path, monkeypatch):
    """Fresh module per test with all I/O paths redirected into tmp_path.
    Caller is responsible for populating messages.db (or leaving it
    missing for the sqlite-error path)."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    messages_db = tmp_path / "messages.db"
    state_path = tmp_path / "session-state.json"
    sentinel = tmp_path / "session_bootstrapped"

    module = load_script(f"register_session_{tmp_path.name}", SCRIPT_REL)
    monkeypatch.setattr(module, "MESSAGES_DB", str(messages_db))
    monkeypatch.setattr(module, "STATE_PATH", str(state_path))
    monkeypatch.setattr(module, "STATE_LOCK_PATH", str(state_path) + ".lock")
    monkeypatch.setattr(module, "SENTINEL", str(sentinel))

    return module, messages_db, state_path, sentinel


def _run_and_capture(module, capsys, argv=()):
    """Run main(); return (exit_code or None, parsed_json_or_None)."""
    rc = None
    try:
        module.main(list(argv))
    except SystemExit as e:
        rc = e.code
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured.splitlines()[-1]) if captured else {}
    return rc, payload


def test_full_roundtrip_writes_state_and_sentinel(register_session, monkeypatch, capsys):
    module, messages_db, state_path, sentinel = register_session
    _make_messages_db(messages_db, "db-session-42")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-99")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None  # main() returns normally on success, no SystemExit
    assert payload == {
        "session_id": "db-session-42",
        "session_name": "default",
        "schema_version": 1,
        "wrote_state": True,
        "wrote_sentinel": True,
    }
    state = json.loads(state_path.read_text())
    assert state["schema_version"] == 1
    assert state["session_id"] == "db-session-42"
    assert state["sessions"]["default"]["session_id"] == "db-session-42"
    assert sentinel.read_text() == "claude-session-99"


@pytest.mark.parametrize("argv", [[], ["--registration-only"]])
def test_resumed_registration_preserves_age_until_session_changes(
    register_session, monkeypatch, capsys, argv
):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, "resumed-session")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "resumed-session")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "maintenance")
    started = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 2, 13, tzinfo=UTC)

    for clock in (started, later):
        monkeypatch.setattr(module, "datetime", Mock(now=Mock(return_value=clock)))
        monkeypatch.setattr(module.time, "time", lambda clock=clock: clock.timestamp())
        rc, payload = _run_and_capture(module, capsys, argv)
        assert rc is None
        assert payload["wrote_state"] is True
        entry = json.loads(state_path.read_text())["sessions"]["maintenance"]
        assert entry == {
            "started": "2026-01-01T00:00:00Z",
            "epoch": 1767225600,
            "session_id": "resumed-session",
            "last_seen": clock.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    # A genuinely new database identity starts a new age under the same name.
    with sqlite3.connect(messages_db) as conn:
        conn.execute("UPDATE sessions SET session_id = 'replacement-session'")
    rc, _ = _run_and_capture(module, capsys, argv)
    assert rc is None
    entry = json.loads(state_path.read_text())["sessions"]["maintenance"]
    assert entry == {
        "started": "2026-02-13T00:00:00Z",
        "epoch": 1770940800,
        "session_id": "replacement-session",
        "last_seen": "2026-02-13T00:00:00Z",
    }


@pytest.mark.parametrize("argv", [[], ["--registration-only"]])
def test_maintenance_rotation_resets_age_with_unconfirmed_db_identity(
    register_session, monkeypatch, capsys, argv
):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, None)
    with sqlite3.connect(messages_db) as conn:
        conn.executemany(
            "INSERT INTO sessions (group_folder, session_name, session_id) VALUES (?, ?, ?)",
            [("main", "default", "default-A"), ("main", "maintenance", "maint-1")],
        )
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "maintenance")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "maint-1")
    started = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 16, tzinfo=UTC)
    monkeypatch.setattr(module, "datetime", Mock(now=Mock(return_value=started)))
    monkeypatch.setattr(module.time, "time", lambda: started.timestamp())
    rc, _ = _run_and_capture(module, capsys, argv)
    assert rc is None

    with sqlite3.connect(messages_db) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (group_folder, session_name, session_id) "
            "VALUES ('main', 'maintenance', 'maint-2')"
        )
    monkeypatch.setenv("CLAUDE_SESSION_ID", "maint-2")
    monkeypatch.setattr(module, "datetime", Mock(now=Mock(return_value=later)))
    monkeypatch.setattr(module.time, "time", lambda: later.timestamp())
    rc, _ = _run_and_capture(module, capsys, argv)
    assert rc is None
    entry = json.loads(state_path.read_text())["sessions"]["maintenance"]
    assert entry["started"] == "2026-01-16T00:00:00Z"
    assert entry["epoch"] == int(later.timestamp())
    assert entry["session_id"] == "default-A"


@pytest.mark.parametrize(
    "previous,session_id",
    [
        (None, "current-session"),
        ([], "current-session"),
        ({"session_id": "current-session"}, "current-session"),
        ({"session_id": None, "started": "old", "epoch": 1}, None),
    ],
)
def test_registration_initializes_age_without_a_known_complete_session(
    register_session, monkeypatch, capsys, previous, session_id
):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, session_id)
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "maintenance")
    clock = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(module, "datetime", Mock(now=Mock(return_value=clock)))
    monkeypatch.setattr(module.time, "time", lambda: 1767225600)
    state_path.write_text(json.dumps({"sessions": {"maintenance": previous}}))

    rc, _ = _run_and_capture(module, capsys, ["--registration-only"])

    assert rc is None
    assert json.loads(state_path.read_text())["sessions"]["maintenance"] == {
        "started": "2026-01-01T00:00:00Z",
        "epoch": 1767225600,
        "session_id": session_id,
        "last_seen": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize("stored", [None, "", "previous-session", "scheduled-session"])
@pytest.mark.parametrize("identity_source", ["CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", None])
def test_scheduled_command_registers_without_changing_bootstrap_state(
    register_session, monkeypatch, capsys, stored, identity_source
):
    """Check both authored prompt routes, then execute their script commands.

    These are bounded Markdown contract checks, not a live model/tool trace.
    """
    module, messages_db, state_path, sentinel = register_session
    _make_messages_db(messages_db, "db-scheduled-session")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    if identity_source:
        monkeypatch.setenv(identity_source, "scheduled-session")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "maintenance")
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sessions": {"default": {"session_id": "interactive-session"}},
                "seen_email_ids": ["message-1"],
            }
        )
    )
    if stored is not None:
        sentinel.write_text(stored)

    rule = (REPO_ROOT / "rules/session-bootstrap.md").read_text()
    for instruction in (
        "Scheduled-task prompts start with the host prefix `[SCHEDULED TASK -`.",
        "Interactive sessions bootstrap before the user's request.",
        "For scheduled-task prompts, the first tool call is the task skill, "
        "with no bootstrap reads.",
        'After the task skill, invoke `Skill(skill: "tessl__trusted-memory")` '
        "Step 1 for registration only.",
        'For interactive sessions, invoke `Skill(skill: "tessl__trusted-memory")` '
        "Step 1 to load group-shared `trusted/` memory, weekly logs, and `highlights.md`.",
        "The skill owns the sentinel check and the single `register-session.py` call; "
        "scheduled prompts skip the check.",
    ):
        assert f"- {instruction}" in rule.splitlines()

    skill = (REPO_ROOT / "skills/trusted-memory/SKILL.md").read_text()
    step = skill.split("## Step 1 — Bootstrap the Session\n", 1)[1].split("\n## Step 2", 1)[0]
    scheduled, interactive = step.split("The agent-runner's `session-start-auto-context`", 1)
    assert (
        "For scheduled-task prompts starting with the host prefix `[SCHEDULED TASK -`, "
        "skip the sentinel check and reads 1–6. "
        "Run this registration-only command after the task skill:"
    ) in scheduled
    assert "Finish here, silent; do not proceed to Step 4." in scheduled
    (scheduled_command,) = [
        shlex.split(line) for line in scheduled.splitlines() if line.startswith("python3 ")
    ]
    check_command, interactive_command = [
        shlex.split(line) for line in interactive.splitlines() if line.startswith("python3 ")
    ]
    script_root = "/home/node/.claude/skills/tessl__trusted-memory/scripts/"
    assert scheduled_command == [
        "python3",
        script_root + "register-session.py",
        "--registration-only",
    ]
    assert check_command == ["python3", script_root + "needs-bootstrap.py"]
    assert interactive_command == ["python3", script_root + "register-session.py"]
    assert "If bootstrap is NOT needed → finish here, silent." in interactive
    assert "If bootstrap IS needed → run these reads in order:" in interactive
    assert [
        line.split("`")[1]
        for line in interactive.splitlines()
        if line.startswith(tuple(f"{number}. Read " for number in range(1, 7)))
    ] == [
        "/workspace/trusted/MEMORY.md",
        "/workspace/trusted/RUNBOOK.md",
        "/workspace/group/memory/daily/",
        "/workspace/group/memory/weekly/",
        "/workspace/trusted/memory/daily/",
        "/workspace/trusted/highlights.md",
    ]
    assert interactive.index(check_command[1]) < interactive.index("1. Read ")
    assert interactive.index("6. Read ") < interactive.index(interactive_command[1])
    assert "proceed to Step 4" in interactive
    scheduled_argv, interactive_argv = scheduled_command[2:], interactive_command[2:]

    # Run the authored scheduled command twice to exercise repeat registration.
    for _ in range(2):
        rc, payload = _run_and_capture(module, capsys, scheduled_argv)
        assert rc is None
        assert payload == {
            "session_id": "db-scheduled-session",
            "session_name": "maintenance",
            "schema_version": 1,
            "wrote_state": True,
            "wrote_sentinel": False,
        }
        state = json.loads(state_path.read_text())
        assert state["schema_version"] == 1
        assert state["session_id"] == "db-scheduled-session"
        assert state["sessions"]["maintenance"]["session_id"] == "db-scheduled-session"
        assert state["sessions"]["default"] == {"session_id": "interactive-session"}
        assert state["seen_email_ids"] == ["message-1"]
        if stored is None:
            assert not sentinel.exists()
        else:
            assert sentinel.read_text() == stored

    # A later interactive turn with this identity must still bootstrap unless
    # a matching sentinel already existed before the scheduled registration.
    monkeypatch.setenv("CLAUDE_SESSION_ID", "scheduled-session")
    reader = load_script(
        "needs_bootstrap_after_scheduled", "skills/trusted-memory/scripts/needs-bootstrap.py"
    )
    monkeypatch.setattr(reader, "SENTINEL", str(sentinel))
    with pytest.raises(SystemExit) as outcome:
        reader.main()
    already_bootstrapped = stored == "scheduled-session"
    assert outcome.value.code == (1 if already_bootstrapped else 0)
    assert json.loads(capsys.readouterr().out)["needs_bootstrap"] is not already_bootstrapped

    # Normal registration after interactive reads still completes bootstrap.
    rc, payload = _run_and_capture(module, capsys, interactive_argv)
    assert rc is None
    assert payload["wrote_sentinel"] is True
    assert sentinel.read_text() == "scheduled-session"
    with pytest.raises(SystemExit) as outcome:
        reader.main()
    assert outcome.value.code == 1
    assert json.loads(capsys.readouterr().out)["needs_bootstrap"] is False


@pytest.mark.parametrize(
    "path,original,replacement",
    [
        (
            "rules/session-bootstrap.md",
            "the first tool call is the task skill, with no bootstrap reads",
            "bootstrap before calling the task skill",
        ),
        (
            "rules/session-bootstrap.md",
            "Interactive sessions bootstrap before the user's request.",
            "Interactive sessions skip bootstrap.",
        ),
        (
            "skills/trusted-memory/SKILL.md",
            "skip the sentinel check and reads 1–6",
            "bootstrap before every task",
        ),
        (
            "skills/trusted-memory/SKILL.md",
            "Finish here, silent; do not proceed to Step 4.",
            "Continue to Step 4.",
        ),
        (
            "skills/trusted-memory/SKILL.md",
            "4. Read the most recent 2 files from `/workspace/group/memory/weekly/`",
            "4. Skip `/workspace/group/memory/weekly/`",
        ),
    ],
    ids=["task-first", "interactive-bootstrap", "scheduled-guard", "scheduled-stop", "weekly"],
)
def test_prompt_route_regressions_are_rejected(
    register_session, monkeypatch, capsys, tmp_path, path, original, replacement
):
    # Mutate only the prompt contracts, retaining the valid registration commands.
    # The route test must reject these even when registration itself still works.
    contract_root = tmp_path / "contracts"
    for relative in ("rules/session-bootstrap.md", "skills/trusted-memory/SKILL.md"):
        text = (REPO_ROOT / relative).read_text()
        if relative == path:
            assert original in text
            text = text.replace(original, replacement, 1)
        target = contract_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    monkeypatch.setattr(__name__ + ".REPO_ROOT", contract_root)

    with pytest.raises(AssertionError):
        test_scheduled_command_registers_without_changing_bootstrap_state(
            register_session, monkeypatch, capsys, stored=None, identity_source="CLAUDE_SESSION_ID"
        )


@pytest.mark.parametrize("failure", ["lock", "state_read", "state_write"])
def test_registration_only_reports_io_failure_without_stamping_sentinel(
    register_session, monkeypatch, capsys, failure
):
    module, messages_db, state_path, sentinel = register_session
    _make_messages_db(messages_db, "db-session")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "scheduled-session")
    sentinel.write_text("previous-session")
    if failure == "lock":
        monkeypatch.setattr(module, "STATE_LOCK_PATH", str(state_path / "missing" / "lock"))
        expected_diagnostic = "cannot open lock file"
    elif failure == "state_read":
        state_path.mkdir()
        expected_diagnostic = "state file read failed"
    else:

        def fail_write(path, data):
            raise OSError("test state write failure")

        monkeypatch.setattr(module, "atomic_write_json", fail_write)
        expected_diagnostic = "failed to write"

    with pytest.raises(SystemExit) as outcome:
        module.main(["--registration-only"])
    captured = capsys.readouterr()
    assert outcome.value.code == 1
    assert captured.out == ""
    assert expected_diagnostic in captured.err
    assert sentinel.read_text() == "previous-session"


def test_missing_claude_session_id_skips_sentinel(register_session, monkeypatch, capsys):
    module, messages_db, state_path, sentinel = register_session
    _make_messages_db(messages_db, "db-session-7")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None
    assert payload["wrote_state"] is True
    assert payload["wrote_sentinel"] is False
    assert state_path.exists()
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "legacy,code,expected",
    [
        (None, "code-A", "code-A"),
        ("", "code-A", "code-A"),
        ("legacy-A", "code-A", "legacy-A"),
        ("legacy-A", None, "legacy-A"),
    ],
)
def test_shared_identity_roundtrip_skips_same_session_and_reboots_new_one(
    register_session, monkeypatch, capsys, legacy, code, expected
):
    module, messages_db, state_path, sentinel = register_session
    _make_messages_db(messages_db, "db-session")
    for name, value in [("CLAUDE_SESSION_ID", legacy), ("CLAUDE_CODE_SESSION_ID", code)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    _, result = _run_and_capture(module, capsys)
    assert result["wrote_sentinel"] is True
    assert sentinel.read_text() == expected
    assert json.loads(state_path.read_text())["session_id"] == "db-session"

    reader = load_script(
        "needs_bootstrap_roundtrip", "skills/trusted-memory/scripts/needs-bootstrap.py"
    )
    monkeypatch.setattr(reader, "SENTINEL", str(sentinel))
    with pytest.raises(SystemExit) as outcome:
        reader.main()
    assert outcome.value.code == 1
    assert json.loads(capsys.readouterr().out)["needs_bootstrap"] is False

    source = "CLAUDE_SESSION_ID" if legacy else "CLAUDE_CODE_SESSION_ID"
    monkeypatch.setenv(source, "next-session")
    with pytest.raises(SystemExit) as outcome:
        reader.main()
    assert outcome.value.code == 0
    assert json.loads(capsys.readouterr().out)["reason"] == "sentinel_mismatch"


def test_sqlite_error_falls_back_to_null_session_id(register_session, monkeypatch, capsys):
    module, messages_db, state_path, _sentinel = register_session
    # messages.db intentionally not created — sqlite3.connect() will
    # create an empty file, then the SELECT against a missing `sessions`
    # table raises sqlite3.OperationalError (a subclass of sqlite3.Error).
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-1")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None
    assert payload["session_id"] is None
    assert payload["wrote_state"] is True
    state = json.loads(state_path.read_text())
    assert state["sessions"]["default"]["session_id"] is None
    assert state["session_id"] is None


def test_legacy_unversioned_state_upgrades_to_v1(register_session, monkeypatch, capsys):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, "db-session-x")
    # Pre-existing legacy file (pre-PR jbaruch/nanoclaw#55 shape) has
    # only the top-level session_id and no `sessions` subtree, no
    # schema_version field.
    state_path.write_text(json.dumps({"session_id": "old-stamp"}))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-2")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")

    _run_and_capture(module, capsys)

    state = json.loads(state_path.read_text())
    assert state["schema_version"] == 1
    assert state["sessions"]["default"]["session_id"] == "db-session-x"
    # Top-level session_id is overwritten to current; legacy field
    # stays present for back-compat readers per state-schema.md.
    assert state["session_id"] == "db-session-x"


def test_corrupt_state_json_starts_fresh(register_session, monkeypatch, capsys):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, "db-session-y")
    state_path.write_text("not json at all {{")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-3")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "maintenance")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None
    assert payload["wrote_state"] is True
    state = json.loads(state_path.read_text())
    assert state["schema_version"] == 1
    assert "maintenance" in state["sessions"]
