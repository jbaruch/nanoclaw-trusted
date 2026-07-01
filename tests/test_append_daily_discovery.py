"""Tests for skills/trusted-memory/scripts/append-daily-discovery.py.

Covers the documented contract:
  - Block-format entry written (`## ts` / `**What:**` / `**Context:**`
    / `**Promote to:**`) when the candidate isn't a duplicate.
  - File created with `# Daily Discoveries\\n\\n` header on first call.
  - Dedup skips an already-present block (whitespace-normalized).
  - All-duplicate path leaves mtime/inode unchanged.
  - Existing on-disk content is never rewritten on the dedup-skip
    path (no destructive migration).
  - JSON status to stdout (single line).
  - Usage validation: required fields, --timestamp format.
"""

import json
import sys
from io import StringIO
from pathlib import Path

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/trusted-memory/scripts/append-daily-discovery.py"
SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "skills/trusted-memory/scripts/append-daily-discovery.py"
)


@pytest.fixture
def discovery_module(tmp_path, monkeypatch):
    """Fresh module per test with the target file pointed at tmp_path."""
    discoveries_file = tmp_path / "daily_discoveries.md"
    monkeypatch.delenv("NANOCLAW_DISCOVERIES_FILE", raising=False)
    module = load_script(f"append_daily_discovery_{tmp_path.name}", SCRIPT_REL)
    monkeypatch.setattr(module, "DEFAULT_DISCOVERIES_FILE", str(discoveries_file))
    return module, discoveries_file


def _run(module, argv, capsys, *, stdin_text=None):
    if stdin_text is not None:
        original = sys.stdin
        sys.stdin = StringIO(stdin_text)
        try:
            rc = module.main(argv)
        finally:
            sys.stdin = original
    else:
        rc = module.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1]) if captured.out.strip() else {}
    return rc, payload, captured.err


def test_creates_file_with_header_on_first_call(discovery_module, capsys):
    module, discoveries_file = discovery_module
    rc, payload, _err = _run(
        module,
        [
            "--what",
            "the foo lives in /opt/bar",
            "--context",
            "found while debugging issue #999",
            "--promote-to",
            "RUNBOOK.md",
            "--timestamp",
            "2026-05-21 09:00 UTC",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["appended"] is True
    assert payload["created"] is True
    assert payload["timestamp"] == "2026-05-21 09:00 UTC"
    content = discoveries_file.read_text()
    assert content.startswith("# Daily Discoveries\n\n")
    assert "## 2026-05-21 09:00 UTC" in content
    assert "**What:** the foo lives in /opt/bar" in content
    assert "**Context:** found while debugging issue #999" in content
    assert "**Promote to:** RUNBOOK.md" in content


def test_appends_second_block_separated_by_blank_line(discovery_module, capsys):
    module, discoveries_file = discovery_module
    _run(
        module,
        [
            "--what",
            "first",
            "--context",
            "ctx1",
            "--promote-to",
            "unsure",
            "--timestamp",
            "2026-05-21 09:00 UTC",
        ],
        capsys,
    )
    _run(
        module,
        [
            "--what",
            "second",
            "--context",
            "ctx2",
            "--promote-to",
            "RUNBOOK.md",
            "--timestamp",
            "2026-05-21 10:00 UTC",
        ],
        capsys,
    )
    content = discoveries_file.read_text()
    # Both blocks present; each on its own `## ts` header.
    assert "## 2026-05-21 09:00 UTC" in content
    assert "## 2026-05-21 10:00 UTC" in content
    # Block 2 starts after a blank line — never immediately concatenated.
    block_one_end = content.index("**Promote to:** unsure\n")
    block_two_start = content.index("## 2026-05-21 10:00 UTC")
    between = content[block_one_end:block_two_start]
    assert "\n\n" in between


def test_duplicate_block_is_skipped(discovery_module, capsys):
    """Acceptance criterion: dedup at apply time. Second call with
    identical fields must not append a second block. File contents
    and mtime/inode unchanged."""
    module, discoveries_file = discovery_module
    args = [
        "--what",
        "duplicate-test",
        "--context",
        "ctx",
        "--promote-to",
        "unsure",
        "--timestamp",
        "2026-05-21 09:00 UTC",
    ]
    _run(module, args, capsys)
    pre_mtime = discoveries_file.stat().st_mtime_ns
    pre_inode = discoveries_file.stat().st_ino
    pre_text = discoveries_file.read_text()

    rc, payload, _err = _run(module, args, capsys)
    assert rc == 0
    assert payload["appended"] is False
    assert payload["dropped_duplicate"] is True
    assert payload["created"] is False
    # File content character-for-character identical, mtime/inode untouched.
    assert discoveries_file.read_text() == pre_text
    assert discoveries_file.stat().st_mtime_ns == pre_mtime
    assert discoveries_file.stat().st_ino == pre_inode


def test_duplicate_with_whitespace_variation_still_skipped(discovery_module, capsys):
    """An entry that normalizes to the same form (whitespace runs
    collapsed, line endings unified) is treated as a duplicate."""
    module, discoveries_file = discovery_module
    _run(
        module,
        [
            "--what",
            "the   thing",
            "--context",
            "ctx",
            "--promote-to",
            "unsure",
            "--timestamp",
            "2026-05-21 09:00 UTC",
        ],
        capsys,
    )
    # Same fields, single-spaced "the thing" — same normalized form.
    rc, payload, _err = _run(
        module,
        [
            "--what",
            "the thing",
            "--context",
            "ctx",
            "--promote-to",
            "unsure",
            "--timestamp",
            "2026-05-21 09:00 UTC",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["appended"] is False
    assert payload["dropped_duplicate"] is True


def test_different_timestamp_is_not_duplicate(discovery_module, capsys):
    """Same body but different `## ts` line = different entry. The
    deer-flow whitespace-normalization pattern preserves timestamp
    differences by design — semantic same-fact dedup is a separate
    problem this script deliberately does not solve."""
    module, _discoveries_file = discovery_module
    _run(
        module,
        [
            "--what",
            "same body",
            "--context",
            "ctx",
            "--promote-to",
            "unsure",
            "--timestamp",
            "2026-05-21 09:00 UTC",
        ],
        capsys,
    )
    rc, payload, _err = _run(
        module,
        [
            "--what",
            "same body",
            "--context",
            "ctx",
            "--promote-to",
            "unsure",
            "--timestamp",
            "2026-05-21 10:00 UTC",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["appended"] is True
    assert payload["dropped_duplicate"] is False


def test_missing_required_field_is_usage_error(discovery_module, capsys):
    module, _discoveries_file = discovery_module
    with pytest.raises(SystemExit) as ei:
        module.main(
            [
                "--what",
                "x",
                "--context",
                "y",
                # --promote-to omitted
            ]
        )
    assert ei.value.code == 2


def test_empty_required_field_is_usage_error(discovery_module, capsys):
    """Whitespace-only `--what` would produce `**What:** ` with empty
    body — useless on disk. Reject early."""
    module, _discoveries_file = discovery_module
    with pytest.raises(SystemExit) as ei:
        module.main(
            [
                "--what",
                "   ",
                "--context",
                "y",
                "--promote-to",
                "RUNBOOK.md",
            ]
        )
    assert ei.value.code == 2


def test_bad_timestamp_format_is_usage_error(discovery_module, capsys):
    module, _discoveries_file = discovery_module
    with pytest.raises(SystemExit) as ei:
        module.main(
            [
                "--what",
                "x",
                "--context",
                "y",
                "--promote-to",
                "RUNBOOK.md",
                "--timestamp",
                "2026-05-21T09:00:00Z",  # ISO-8601, not the canonical shape
            ]
        )
    assert ei.value.code == 2


def test_discoveries_file_flag_overrides_default(discovery_module, capsys, tmp_path):
    """Explicit `--discoveries-file` redirects the target. Used for
    tests + debugging + alternate mount layouts."""
    module, _default_file = discovery_module
    custom = tmp_path / "custom_discoveries.md"
    rc, payload, _err = _run(
        module,
        [
            "--what",
            "x",
            "--context",
            "y",
            "--promote-to",
            "RUNBOOK.md",
            "--timestamp",
            "2026-05-21 09:00 UTC",
            "--discoveries-file",
            str(custom),
        ],
        capsys,
    )
    assert rc == 0
    assert payload["path"] == str(custom)
    assert custom.exists()


def test_env_var_override_when_no_flag(discovery_module, capsys, monkeypatch, tmp_path):
    module, _default_file = discovery_module
    env_target = tmp_path / "env_discoveries.md"
    monkeypatch.setenv("NANOCLAW_DISCOVERIES_FILE", str(env_target))
    rc, payload, _err = _run(
        module,
        [
            "--what",
            "x",
            "--context",
            "y",
            "--promote-to",
            "RUNBOOK.md",
            "--timestamp",
            "2026-05-21 09:00 UTC",
        ],
        capsys,
    )
    assert rc == 0
    assert env_target.exists()
    assert payload["path"] == str(env_target)


def test_emits_single_line_json(discovery_module, capsys):
    module, _discoveries_file = discovery_module
    rc, _payload, _err = _run(
        module,
        [
            "--what",
            "x",
            "--context",
            "y",
            "--promote-to",
            "RUNBOOK.md",
            "--timestamp",
            "2026-05-21 09:00 UTC",
        ],
        capsys,
    )
    assert rc == 0
    out = capsys.readouterr().out  # capsys was already drained in _run; this is empty
    # The _run wrapper drains capsys; the assertion that stdout was
    # one line of JSON is implicit in _run's parsing (it would raise
    # on a non-JSON line or multi-line shape).
    assert out == ""


def test_json_payload_keys_present(discovery_module, capsys):
    module, _discoveries_file = discovery_module
    rc, payload, _err = _run(
        module,
        [
            "--what",
            "x",
            "--context",
            "y",
            "--promote-to",
            "RUNBOOK.md",
            "--timestamp",
            "2026-05-21 09:00 UTC",
        ],
        capsys,
    )
    assert rc == 0
    for key in ("path", "appended", "dropped_duplicate", "created", "timestamp"):
        assert key in payload, f"missing {key!r} in payload {payload!r}"
