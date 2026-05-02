"""Tests for skills/trusted-memory/scripts/append-to-daily-log.py.

Covers the documented contract:
  - Lock-serialised read-modify-write cycle on the daily file.
  - File creation with `# Daily Summary — YYYY-MM-DD\n\n` header on absent target.
  - Lines appended at end-of-file regardless of timestamp ordering.
  - Out-of-order detection: stderr warning + result['out_of_order']=True
    when the first new line's HH:MM is BEFORE the existing file's last
    HH:MM.
  - JSON status to stdout.
  - File mode preserved across overwrites (mkstemp's 0600 mode is
    chmod-corrected before os.replace).
  - Concurrent writers serialised — two processes appending at once
    each see their lines land, none clobber the other.
"""

import json
import multiprocessing as mp
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/trusted-memory/scripts/append-to-daily-log.py"
SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "skills/trusted-memory/scripts/append-to-daily-log.py"
)


@pytest.fixture
def append_module(tmp_path, monkeypatch):
    """Fresh module per test with the daily-dir constants redirected
    into tmp_path. Returns (module, group_dir, trusted_dir).

    Clears `NANOCLAW_GROUP_DAILY` / `NANOCLAW_TRUSTED_DAILY` from the
    test runner's environment up front. Without that delete, a
    runner that happened to have the env vars set would route writes
    into the env-var path instead of the monkeypatched module
    constants — tests that depend on tmp_path would silently land in
    the wrong directory and false-pass. The override-precedence tests
    below set their OWN env vars via `monkeypatch.setenv` after this
    fixture runs, so the deletion here doesn't interfere with them."""
    group_dir = tmp_path / "group/memory/daily"
    trusted_dir = tmp_path / "trusted/memory/daily"
    monkeypatch.delenv("NANOCLAW_GROUP_DAILY", raising=False)
    monkeypatch.delenv("NANOCLAW_TRUSTED_DAILY", raising=False)
    module = load_script(f"append_to_daily_log_{tmp_path.name}", SCRIPT_REL)
    monkeypatch.setattr(module, "GROUP_DAILY_DIR", str(group_dir))
    monkeypatch.setattr(module, "TRUSTED_DAILY_DIR", str(trusted_dir))
    return module, group_dir, trusted_dir


def _run(module, argv, capsys, stdin_text=None):
    """Invoke main(argv); return (rc, payload, stderr)."""
    if stdin_text is not None:
        original = sys.stdin
        from io import StringIO

        sys.stdin = StringIO(stdin_text)
        try:
            rc = module.main(argv)
        finally:
            sys.stdin = original
    else:
        rc = module.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1]) if captured.out.strip() else None
    return rc, payload, captured.err


def test_creates_file_with_header_on_first_call(append_module, capsys):
    module, group_dir, _ = append_module
    rc, payload, _err = _run(
        module,
        ["--target", "group", "--date", "2026-05-01", "--line", "- 09:00 UTC — first"],
        capsys,
    )
    assert rc == 0
    daily_file = group_dir / "2026-05-01.md"
    assert daily_file.exists()
    content = daily_file.read_text()
    assert content.startswith("# Daily Summary — 2026-05-01\n\n")
    assert "- 09:00 UTC — first\n" in content
    assert payload["created"] is True
    assert payload["appended_lines"] == 1
    assert payload["out_of_order"] is False


def test_appends_to_existing_file_without_clobbering(append_module, capsys):
    module, group_dir, _ = append_module
    daily_file = group_dir / "2026-05-01.md"
    daily_file.parent.mkdir(parents=True, exist_ok=True)
    daily_file.write_text("# Daily Summary — 2026-05-01\n\n- 09:00 UTC — earlier entry\n")

    rc, payload, _err = _run(
        module,
        ["--target", "group", "--date", "2026-05-01", "--line", "- 10:30 UTC — later entry"],
        capsys,
    )
    assert rc == 0
    content = daily_file.read_text()
    assert "- 09:00 UTC — earlier entry" in content
    assert "- 10:30 UTC — later entry" in content
    assert payload["created"] is False
    assert payload["out_of_order"] is False


def test_multiple_lines_via_repeated_flag(append_module, capsys):
    module, _group_dir, trusted_dir = append_module
    rc, payload, _err = _run(
        module,
        [
            "--target",
            "trusted",
            "--date",
            "2026-05-01",
            "--line",
            "- 11:00 UTC [main] — one",
            "--line",
            "- 11:05 UTC [main] — two",
            "--line",
            "- 11:10 UTC [main] — three",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["appended_lines"] == 3
    content = (trusted_dir / "2026-05-01.md").read_text()
    assert content.count("- 11:") == 3


def test_lines_file(append_module, tmp_path, capsys):
    module, group_dir, _ = append_module
    lines_file = tmp_path / "lines.txt"
    lines_file.write_text("- 12:00 UTC — alpha\n- 12:05 UTC — beta\n")

    rc, payload, _err = _run(
        module,
        ["--target", "group", "--date", "2026-05-01", "--lines-file", str(lines_file)],
        capsys,
    )
    assert rc == 0
    assert payload["appended_lines"] == 2


def test_stdin_when_no_flags(append_module, capsys):
    module, group_dir, _ = append_module
    rc, payload, _err = _run(
        module,
        ["--target", "group", "--date", "2026-05-01"],
        capsys,
        stdin_text="- 13:00 UTC — from stdin\n",
    )
    assert rc == 0
    assert payload["appended_lines"] == 1


def test_empty_input_is_usage_error(append_module, capsys):
    module, _group_dir, _ = append_module
    with pytest.raises(SystemExit) as ei:
        _run(
            module,
            ["--target", "group", "--date", "2026-05-01"],
            capsys,
            stdin_text="",
        )
    assert ei.value.code == 2


def test_line_and_lines_file_together_is_usage_error(append_module, tmp_path, capsys):
    module, _group_dir, _ = append_module
    lines_file = tmp_path / "lines.txt"
    lines_file.write_text("- 09:00 UTC — x\n")
    with pytest.raises(SystemExit) as ei:
        _run(
            module,
            [
                "--target",
                "group",
                "--date",
                "2026-05-01",
                "--line",
                "- 10:00 UTC — y",
                "--lines-file",
                str(lines_file),
            ],
            capsys,
        )
    assert ei.value.code == 2


def test_bad_date_format_is_usage_error(append_module, capsys):
    module, _group_dir, _ = append_module
    with pytest.raises(SystemExit) as ei:
        _run(
            module,
            ["--target", "group", "--date", "2026/05/01", "--line", "- 09:00 UTC — x"],
            capsys,
        )
    assert ei.value.code == 2


def test_out_of_order_warns_but_appends(append_module, capsys):
    module, group_dir, _ = append_module
    daily_file = group_dir / "2026-05-01.md"
    daily_file.parent.mkdir(parents=True, exist_ok=True)
    daily_file.write_text("# Daily Summary — 2026-05-01\n\n- 14:00 UTC — late\n")

    rc, payload, err = _run(
        module,
        ["--target", "group", "--date", "2026-05-01", "--line", "- 09:00 UTC — earlier"],
        capsys,
    )
    assert rc == 0
    assert payload["out_of_order"] is True
    assert "out-of-order" in err
    # Despite the warning, the line MUST land — silent reorder would
    # mask actual bugs in cross-group writers.
    content = daily_file.read_text()
    assert "- 09:00 UTC — earlier" in content


def test_file_mode_preserved_across_overwrite(append_module, capsys):
    module, group_dir, _ = append_module
    daily_file = group_dir / "2026-05-01.md"
    daily_file.parent.mkdir(parents=True, exist_ok=True)
    daily_file.write_text("# Daily Summary — 2026-05-01\n\n- 09:00 UTC — x\n")
    os.chmod(daily_file, 0o640)

    _run(
        module,
        ["--target", "group", "--date", "2026-05-01", "--line", "- 10:00 UTC — y"],
        capsys,
    )

    mode = stat.S_IMODE(os.stat(daily_file).st_mode)
    assert mode == 0o640


def _child_append(daily_file_path, lines, target):
    """Subprocess worker: invoke the script as a CLI so each writer
    gets a fresh process with its own file descriptors. Lock contention
    is what we're actually testing — module-level reentry would all
    happen in-process and not exercise the OS lock."""
    cmd = [sys.executable, str(SCRIPT_PATH), "--target", target, "--date", "2026-05-01"]
    for ln in lines:
        cmd.extend(["--line", ln])
    env = os.environ.copy()
    # Override constants by injecting the parent dirs via env-aware
    # path… but the script uses module constants, not env. Easiest
    # path: set the daily file directly via a wrapper that monkey-
    # patches before main() runs.
    wrapper = f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location('m', {str(SCRIPT_PATH)!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.GROUP_DAILY_DIR = {str(daily_file_path.parent)!r}
m.TRUSTED_DAILY_DIR = {str(daily_file_path.parent)!r}
sys.exit(m.main(sys.argv[1:]))
"""
    proc = subprocess.run(
        [sys.executable, "-c", wrapper, *cmd[2:]],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_concurrent_writers_serialise_via_lock(tmp_path):
    """Two subprocesses each append 50 unique lines simultaneously.
    Without LOCK_EX the read-modify-write cycle would race and one
    writer's contribution would be lost. Assert all 100 lines land."""
    daily_dir = tmp_path / "group/memory/daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_file = daily_dir / "2026-05-01.md"

    # Pre-create the file so both writers race the read-modify-write
    # path rather than the create path.
    daily_file.write_text("# Daily Summary — 2026-05-01\n\n")

    a_lines = [f"- 09:{i:02d} UTC — A{i}" for i in range(50)]
    b_lines = [f"- 10:{i:02d} UTC — B{i}" for i in range(50)]

    with mp.Pool(2) as pool:
        results = pool.starmap(
            _child_append,
            [(daily_file, a_lines, "group"), (daily_file, b_lines, "group")],
        )

    for rc, _stdout, stderr in results:
        assert rc == 0, f"subprocess failed: {stderr}"

    content = daily_file.read_text()
    for line in a_lines + b_lines:
        assert line in content, f"missing {line!r} — concurrent clobber"


def test_emits_single_line_json(tmp_path):
    """Run via subprocess so we observe the actual stdout bytes
    instead of going through capsys-after-main(). The single-line
    contract is what callers (and CI step output parsers) depend on
    — pretty-printed JSON would break the parsing pattern."""
    daily_dir = tmp_path / "group/memory/daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    wrapper = f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location('m', {str(SCRIPT_PATH)!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.GROUP_DAILY_DIR = {str(daily_dir)!r}
m.TRUSTED_DAILY_DIR = {str(daily_dir)!r}
sys.exit(m.main(sys.argv[1:]))
"""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            wrapper,
            "--target",
            "group",
            "--date",
            "2026-05-01",
            "--line",
            "- 09:00 UTC — x",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"subprocess failed: {proc.stderr}"
    # Stdout is exactly one line of JSON with a trailing newline,
    # nothing more — `print(json.dumps(...))` produces this shape.
    out_lines = proc.stdout.splitlines()
    assert len(out_lines) == 1, f"expected 1 line of stdout, got {len(out_lines)}: {proc.stdout!r}"
    payload = json.loads(out_lines[0])
    for key in ("path", "appended_lines", "final_line_count", "created", "out_of_order"):
        assert key in payload


def test_trusted_target_resolves_to_trusted_path(append_module, capsys):
    module, _group_dir, trusted_dir = append_module
    _run(
        module,
        ["--target", "trusted", "--date", "2026-05-01", "--line", "- 09:00 UTC [main] — t"],
        capsys,
    )
    assert (trusted_dir / "2026-05-01.md").exists()


def test_header_matches_archive_helper_regex(append_module, capsys):
    """archive-helper.py in nanoclaw-admin/skills/nightly-housekeeping
    archives both /workspace/group/memory/daily/ AND /workspace/trusted/
    memory/daily/ via a daily-header regex `^# Daily Summary —
    \\d{4}-\\d{2}-\\d{2}\\s*$` (the `\\s*$` tolerates trailing
    whitespace, common when an editor strips/preserves trailing
    blanks asymmetrically). If our header diverges, archive-helper
    silently skips the file and daily logs accumulate forever in
    daily/. Lock the canonical wording in so a future "let's tighten
    the header style" change can't regress this without breaking the
    test."""
    import re

    module, group_dir, _ = append_module
    _run(
        module,
        ["--target", "group", "--date", "2026-05-01", "--line", "- 09:00 UTC — x"],
        capsys,
    )
    content = (group_dir / "2026-05-01.md").read_text()
    first_line = content.splitlines()[0]
    archive_helper_regex = re.compile(r"^# Daily Summary — \d{4}-\d{2}-\d{2}\s*$")
    assert archive_helper_regex.match(first_line), (
        f"first line {first_line!r} doesn't match archive-helper.py's "
        f"daily-header regex; archived rotation will skip this file"
    )


def test_group_daily_flag_overrides_default(append_module, tmp_path, capsys):
    """`--group-daily <path>` redirects the target dir for production
    callers whose memory tree isn't at the canonical /workspace path
    (test runners, alternate mount layouts, debugging)."""
    module, _, _ = append_module
    custom_dir = tmp_path / "custom-group-daily"
    rc, payload, _err = _run(
        module,
        [
            "--target",
            "group",
            "--date",
            "2026-05-01",
            "--group-daily",
            str(custom_dir),
            "--line",
            "- 09:00 UTC — x",
        ],
        capsys,
    )
    assert rc == 0
    assert (custom_dir / "2026-05-01.md").exists()
    assert payload["path"] == str(custom_dir / "2026-05-01.md")


def test_trusted_daily_flag_overrides_default(append_module, tmp_path, capsys):
    module, _, _ = append_module
    custom_dir = tmp_path / "custom-trusted-daily"
    rc, payload, _err = _run(
        module,
        [
            "--target",
            "trusted",
            "--date",
            "2026-05-01",
            "--trusted-daily",
            str(custom_dir),
            "--line",
            "- 09:00 UTC [main] — y",
        ],
        capsys,
    )
    assert rc == 0
    assert (custom_dir / "2026-05-01.md").exists()


def test_env_var_override_when_no_flag(monkeypatch, append_module, tmp_path, capsys):
    """When `--group-daily` is omitted the helper falls back to the
    `NANOCLAW_GROUP_DAILY` env var. Container deployments mount the
    memory tree elsewhere via env-var, scripts, or the runtime config."""
    module, _, _ = append_module
    env_dir = tmp_path / "env-group-daily"
    monkeypatch.setenv("NANOCLAW_GROUP_DAILY", str(env_dir))
    rc, _payload, _err = _run(
        module,
        ["--target", "group", "--date", "2026-05-01", "--line", "- 09:00 UTC — z"],
        capsys,
    )
    assert rc == 0
    assert (env_dir / "2026-05-01.md").exists()


def test_flag_wins_over_env_var(monkeypatch, append_module, tmp_path, capsys):
    """Explicit `--group-daily` takes precedence over the env-var
    fallback so tests / debugging invocations aren't silently
    overridden by a sticky env var the operator forgot."""
    module, _, _ = append_module
    flag_dir = tmp_path / "flag-wins"
    env_dir = tmp_path / "env-loses"
    monkeypatch.setenv("NANOCLAW_GROUP_DAILY", str(env_dir))
    rc, _payload, _err = _run(
        module,
        [
            "--target",
            "group",
            "--date",
            "2026-05-01",
            "--group-daily",
            str(flag_dir),
            "--line",
            "- 09:00 UTC — w",
        ],
        capsys,
    )
    assert rc == 0
    assert (flag_dir / "2026-05-01.md").exists()
    assert not (env_dir / "2026-05-01.md").exists()
