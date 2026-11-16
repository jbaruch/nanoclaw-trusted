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
    monkeypatch.setenv("NANOCLAW_GROUP_FOLDER", "telegram_swarm")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "default")
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
    monkeypatch.setenv("CLAUDE_SESSION_ID", "db-session-42")
    monkeypatch.setattr(module.time, "time", lambda: 1770940800)
    state_path.write_text(
        json.dumps(
            {
                "sessions": {
                    "default": {
                        "session_id": "db-session-42",
                        "started": "2026-01-01T00:00:00Z",
                        "epoch": 1767225600,
                    }
                }
            }
        )
    )
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
    assert sentinel.read_text() == "db-session-42"
    entry = state["sessions"]["default"]
    assert entry["epoch"] == 1770940800
    assert entry["started"] == entry["last_seen"]


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
    with sqlite3.connect(messages_db) as conn:
        conn.execute("UPDATE sessions SET session_name = 'maintenance'")
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
        "Scheduled-task prompts contain the host marker `[SCHEDULED TASK -`.",
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
        "For scheduled-task prompts containing the host marker `[SCHEDULED TASK -`, "
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


@pytest.mark.parametrize("existing_db", [False, True], ids=["missing-db", "missing-table"])
def test_unavailable_database_returns_null_without_creating_replacement(
    register_session, monkeypatch, capsys, existing_db
):
    module, messages_db, state_path, _sentinel = register_session
    if existing_db:
        with sqlite3.connect(messages_db):
            pass
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-1")

    module.main([])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert messages_db.exists() is existing_db
    assert payload["session_id"] is None
    assert payload["wrote_state"] is True
    assert str(messages_db) in captured.err
    assert "session_id unavailable" in captured.err
    assert "Check the host messages.db mount and sessions schema" in captured.err
    assert "do not create a replacement" in captured.err
    state = json.loads(state_path.read_text())
    assert state["sessions"]["default"]["session_id"] is None
    assert state["session_id"] is None


def test_database_lookup_and_state_use_both_runtime_keys(register_session, monkeypatch, capsys):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, "other-session")
    with sqlite3.connect(messages_db) as conn:
        conn.execute("INSERT INTO sessions VALUES ('other-group', 'maintenance', 'wrong-group')")
        conn.execute("INSERT INTO sessions VALUES ('telegram_swarm', 'maintenance', 'wanted')")
    monkeypatch.setenv("NANOCLAW_SESSION_NAME", "maintenance")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-1")

    rc, payload = _run_and_capture(module, capsys)

    assert rc is None
    assert payload["session_id"] == "wanted"
    state = json.loads(state_path.read_text())
    assert state["sessions"]["maintenance"]["session_id"] == "wanted"
    assert state["session_id"] == "wanted"


@pytest.mark.parametrize("name", ["NANOCLAW_GROUP_FOLDER", "NANOCLAW_SESSION_NAME"])
@pytest.mark.parametrize("value", [None, ""])
def test_database_lookup_requires_runtime_identity(
    register_session, monkeypatch, capsys, name, value
):
    module, messages_db, state_path, _sentinel = register_session
    _make_messages_db(messages_db, "must-not-borrow")
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-1")

    module.main([])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["session_id"] is None
    state = json.loads(state_path.read_text())
    assert state["session_id"] is None
    assert state["sessions"][payload["session_name"]]["session_id"] is None
    assert "session_id unavailable" in captured.err
    assert name in captured.err
    assert "Run through the host runtime" in captured.err


@pytest.mark.parametrize(
    "name,value",
    [("NANOCLAW_GROUP_FOLDER", "absent-group"), ("NANOCLAW_SESSION_NAME", "maintenance")],
)
def test_database_lookup_does_not_borrow_unmatched_row(
    register_session, monkeypatch, capsys, name, value
):
    module, messages_db, _state_path, _sentinel = register_session
    _make_messages_db(messages_db, "must-not-borrow")
    monkeypatch.setenv(name, value)

    assert module.read_session_id_from_db() is None
    diagnostic = capsys.readouterr().err
    assert "session_id unavailable" in diagnostic
    assert value in diagnostic
    assert "Check the host sessions registration" in diagnostic


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
