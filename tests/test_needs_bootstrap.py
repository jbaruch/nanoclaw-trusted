"""Baseline tests for skills/trusted-memory/scripts/needs-bootstrap.py.

Covers the documented exit-code contract:
  0 — bootstrap IS needed (no sentinel, mismatch, empty env, empty file)
  1 — bootstrap NOT needed (sentinel matches current $CLAUDE_SESSION_ID)
"""

import json

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/trusted-memory/scripts/needs-bootstrap.py"


@pytest.fixture
def needs_bootstrap_module(tmp_path, monkeypatch):
    """Fresh module instance per test with the SENTINEL path redirected
    into tmp_path. The sentinel file is NOT created — callers create it
    when they need a present-sentinel scenario."""
    sentinel = tmp_path / "session_bootstrapped"
    module = load_script(f"needs_bootstrap_{tmp_path.name}", SCRIPT_REL)
    monkeypatch.setattr(module, "SENTINEL", str(sentinel))
    return module, sentinel


def _run_and_capture(module, capsys):
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    out = capsys.readouterr().out
    return excinfo.value.code, json.loads(out.strip().splitlines()[-1])


def test_no_sentinel_file_needs_bootstrap(needs_bootstrap_module, monkeypatch, capsys):
    module, _sentinel = needs_bootstrap_module
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-abc")

    rc, payload = _run_and_capture(module, capsys)

    assert rc == 0
    assert payload == {
        "needs_bootstrap": True,
        "current": "session-abc",
        "stored": None,
        "reason": "sentinel_missing",
    }


def test_sentinel_match_skips_bootstrap(needs_bootstrap_module, monkeypatch, capsys):
    module, sentinel = needs_bootstrap_module
    sentinel.write_text("session-abc")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-abc")

    rc, payload = _run_and_capture(module, capsys)

    assert rc == 1
    assert payload["needs_bootstrap"] is False
    assert payload["reason"] == "sentinel_match"


def test_sentinel_mismatch_needs_bootstrap(needs_bootstrap_module, monkeypatch, capsys):
    module, sentinel = needs_bootstrap_module
    sentinel.write_text("session-old")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-new")

    rc, payload = _run_and_capture(module, capsys)

    assert rc == 0
    assert payload["needs_bootstrap"] is True
    assert payload["stored"] == "session-old"
    assert payload["reason"] == "sentinel_mismatch"


def test_missing_claude_session_id_defaults_to_bootstrap_needed(
    needs_bootstrap_module, monkeypatch, capsys
):
    module, _sentinel = needs_bootstrap_module
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)

    rc, payload = _run_and_capture(module, capsys)

    assert rc == 0
    assert payload["needs_bootstrap"] is True
    assert payload["reason"] == "claude_session_id_missing"


def test_empty_sentinel_file_treated_as_bootstrap_needed(
    needs_bootstrap_module, monkeypatch, capsys
):
    module, sentinel = needs_bootstrap_module
    sentinel.write_text("")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-abc")

    rc, payload = _run_and_capture(module, capsys)

    assert rc == 0
    assert payload["needs_bootstrap"] is True
    assert payload["reason"] == "sentinel_empty"
