"""Tests for skills/trusted-memory/scripts/memory_write.py.

Covers the documented contract:
  - normalize_for_comparison: collapses whitespace runs, normalizes
    line endings, strips edges.
  - dedup_filter: returns kept and dropped lists per line- or block-
    granularity split; within-batch dedup; empty entries dropped.
  - write_atomic: tempfile + fsync + os.replace; preserves existing
    file mode; cleans up tempfile on failure; mid-write crash leaves
    file either pre-state or post-state, never partial.
"""

import importlib.util
import multiprocessing as mp
import os
import signal
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "skills/trusted-memory/scripts/memory_write.py"


@pytest.fixture
def mw():
    """Fresh module per test so monkeypatches don't bleed across cases."""
    spec = importlib.util.spec_from_file_location("memory_write_under_test", HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_collapses_whitespace_runs(mw):
    assert mw.normalize_for_comparison("- 09:00  UTC\t— hello") == "- 09:00 UTC — hello"


def test_normalize_normalizes_line_endings(mw):
    """`\\r\\n` → `\\n`, then collapsed to a single space inside a multi-
    line block. The two strings below are semantically the same entry
    written by callers on different platforms or by an editor that
    fiddles with line endings."""
    crlf = "## 2026-05-21 09:00 UTC\r\n**What:** thing\r\n"
    lf = "## 2026-05-21 09:00 UTC\n**What:** thing\n"
    assert mw.normalize_for_comparison(crlf) == mw.normalize_for_comparison(lf)


def test_normalize_strips_edges(mw):
    assert mw.normalize_for_comparison("   hello world   \n") == "hello world"


def test_normalize_empty_input(mw):
    assert mw.normalize_for_comparison("") == ""
    assert mw.normalize_for_comparison("   \n\t  ") == ""


def test_dedup_filter_line_granularity(mw):
    existing = "# header\n\n- 09:00 UTC — alpha\n- 10:00 UTC — beta\n"
    candidates = [
        "- 09:00 UTC — alpha",  # exact dup
        "- 10:00  UTC — beta",  # whitespace-different dup
        "- 11:00 UTC — gamma",  # new
    ]
    kept, dropped = mw.dedup_filter(existing, candidates, split="\n")
    assert kept == ["- 11:00 UTC — gamma"]
    assert "- 09:00 UTC — alpha" in dropped
    assert "- 10:00  UTC — beta" in dropped


def test_dedup_filter_block_granularity(mw):
    existing = (
        "# Daily Discoveries\n\n"
        "## 2026-05-21 09:00 UTC\n"
        "**What:** thing\n"
        "**Context:** somewhere\n"
        "**Promote to:** unsure\n"
    )
    # Same block, identical text — must dedup.
    dup_block = (
        "## 2026-05-21 09:00 UTC\n"
        "**What:** thing\n"
        "**Context:** somewhere\n"
        "**Promote to:** unsure\n"
    )
    # Different timestamp = different entry; must keep.
    new_block = (
        "## 2026-05-21 10:00 UTC\n"
        "**What:** thing\n"
        "**Context:** somewhere\n"
        "**Promote to:** unsure\n"
    )
    kept, dropped = mw.dedup_filter(existing, [dup_block, new_block], split="\n\n")
    assert kept == [new_block]
    assert dropped == [dup_block]


def test_dedup_filter_within_batch_dedup(mw):
    """A single batch with two identical candidates lands once."""
    existing = ""
    candidates = ["- 09:00 UTC — alpha", "- 09:00  UTC  —  alpha", "- 10:00 UTC — beta"]
    kept, dropped = mw.dedup_filter(existing, candidates, split="\n")
    assert kept == ["- 09:00 UTC — alpha", "- 10:00 UTC — beta"]
    assert dropped == ["- 09:00  UTC  —  alpha"]


def test_dedup_filter_drops_empty_candidates(mw):
    """Whitespace-only candidates are surfaced as dropped, not kept —
    the call site decides whether that's an error or a no-op."""
    existing = ""
    candidates = ["", "   ", "\n\t", "- 09:00 UTC — real"]
    kept, dropped = mw.dedup_filter(existing, candidates, split="\n")
    assert kept == ["- 09:00 UTC — real"]
    assert dropped == ["", "   ", "\n\t"]


def test_dedup_filter_empty_existing(mw):
    """First write to an empty file: every non-empty candidate kept,
    within-batch dedup still applies."""
    kept, dropped = mw.dedup_filter(
        "", ["- 09:00 UTC — a", "- 09:00 UTC — a", "- 10:00 UTC — b"], split="\n"
    )
    assert kept == ["- 09:00 UTC — a", "- 10:00 UTC — b"]
    assert dropped == ["- 09:00 UTC — a"]


def test_write_atomic_creates_file(mw, tmp_path):
    target = tmp_path / "out.txt"
    mw.write_atomic(target, "hello\n")
    assert target.read_text() == "hello\n"


def test_write_atomic_creates_parent_dirs(mw, tmp_path):
    target = tmp_path / "deep/nested/path/out.txt"
    mw.write_atomic(target, "deep\n")
    assert target.read_text() == "deep\n"


def test_write_atomic_preserves_existing_mode(mw, tmp_path):
    """An existing file at 0640 must stay at 0640 after the atomic
    overwrite. mkstemp defaults to 0600, so without the chmod step a
    shared state file would silently get its read bit stripped on the
    first append."""
    target = tmp_path / "modey.txt"
    target.write_text("old\n")
    os.chmod(target, 0o640)
    mw.write_atomic(target, "new\n")
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o640


def test_write_atomic_default_mode_for_new_file(mw, tmp_path):
    target = tmp_path / "fresh.txt"
    mw.write_atomic(target, "fresh\n", default_mode=0o600)
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o600


def test_write_atomic_cleans_tempfile_on_failure(mw, tmp_path, monkeypatch):
    """Force os.replace to raise after the tempfile is written. The
    failure must propagate AND the `.tmp` sibling must not linger —
    a stray tmp from every failure would clutter the directory and
    eventually collide on a new mkstemp suffix."""
    target = tmp_path / "fail.txt"
    target.write_text("original\n")

    real_replace = os.replace

    def boom(_src, _dst):
        raise OSError("simulated EIO")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        mw.write_atomic(target, "newer\n")

    monkeypatch.setattr(os, "replace", real_replace)
    # Original content intact, no stray tempfiles in the parent.
    assert target.read_text() == "original\n"
    tmps = list(tmp_path.glob(".fail.txt.*.tmp"))
    assert tmps == [], f"unexpected tempfile orphan(s): {tmps}"


# ---------------------------------------------------------------------------
# Atomic-write smoke test (acceptance criterion #4):
# "Atomic write covered by a smoke test (e.g., interrupt mid-write, file is
#  either old or new — never partial)."
# ---------------------------------------------------------------------------

# Sentinel value chosen so the partial-write check below can't pass
# coincidentally: the original content is short, the replacement is
# 100x longer. A partial-write would land somewhere between the two,
# detectable by checking that the file's content is exactly one of
# the two well-known strings.
_OLD_CONTENT = "OLD_CONTENT_BEFORE_CRASH\n"
_NEW_CONTENT = ("NEW_CONTENT_AFTER_REPLACE_" * 100) + "\n"


def _child_writer(target_path: str, ready_event, hold_event) -> None:
    """Subprocess body for the smoke test.

    Monkeypatches `os.replace` with a sentinel that:
      1. Signals `ready_event` to tell the parent the child is now
         poised exactly between `fsync` (which already happened
         inside `write_atomic`) and the real `os.replace`.
      2. Blocks on `hold_event` indefinitely.

    The parent observes `ready_event`, issues SIGKILL, then sets
    `hold_event` only as a courtesy in case the test ever skips the
    kill (it won't on the happy path — SIGKILL kills the process
    before the wait returns). Determinism: the child never reaches
    `real_replace` unless the parent fails to kill it within
    `hold_event.wait()`'s timeout, in which case the test fails on
    `exitcode` rather than racing the timing."""
    spec = importlib.util.spec_from_file_location("memory_write_child", HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    real_replace = os.replace

    def gated_replace(src, dst):
        ready_event.set()
        # Block until the parent releases us — but with a finite
        # timeout so a buggy test (parent forgot to kill or release)
        # exits in bounded time. SIGKILL from the parent normally
        # terminates the process during this wait; if not, the wait
        # returns and we proceed to the real replace, which makes
        # the parent's "expected OLD content" assertion fail loudly
        # rather than hang the suite.
        hold_event.wait(timeout=30)
        return real_replace(src, dst)

    os.replace = gated_replace
    module.write_atomic(Path(target_path), _NEW_CONTENT)


def test_atomic_write_smoke_kill_mid_write_leaves_file_intact(tmp_path):
    """Smoke test for acceptance criterion #4. Start the atomic write
    in a subprocess, SIGKILL it after the tempfile is written but
    before `os.replace` runs, then assert the on-disk file is still
    the OLD content — never partial. The complementary "either old
    or new" half is covered by every other test in this file (they
    observe the NEW content); the missing assurance the smoke test
    adds is the "never partial" half on an interrupted call.

    Synchronization is deterministic via `multiprocessing.Event` —
    the child signals `ready_event` immediately before the would-be
    `os.replace` call, and only after the parent observes that
    signal does it issue SIGKILL. No sleep-based timing, no CI-load
    race per `jbaruch/coding-policy: testing-standards`.

    SIGKILL was picked over SIGTERM because Python's atexit and
    finalizers can run on SIGTERM and might still complete the
    `os.replace`; SIGKILL guarantees the process dies before the
    rename step."""
    target = tmp_path / "victim.txt"
    target.write_text(_OLD_CONTENT)
    os.chmod(target, 0o640)

    ctx = mp.get_context("spawn")
    ready_event = ctx.Event()
    hold_event = ctx.Event()  # never set by the parent; SIGKILL ends the child first
    proc = ctx.Process(target=_child_writer, args=(str(target), ready_event, hold_event))
    proc.start()
    # Deterministic wait: returns as soon as the child enters
    # `gated_replace`, regardless of CI load. The timeout exists as
    # a backstop — if the child never reaches that point (import
    # failure, mkstemp failure on the test runner) the test fails
    # here instead of hanging.
    assert ready_event.wait(timeout=30), (
        "child never entered gated_replace; mkstemp/fsync likely failed "
        "before reaching the os.replace seam — check stderr from the child"
    )
    os.kill(proc.pid, signal.SIGKILL)
    proc.join(timeout=5)

    assert proc.exitcode is not None, "child process never exited after SIGKILL"
    assert proc.exitcode != 0, "child was supposed to die before completing write_atomic"

    # The cardinal contract: contents are either OLD (no replace
    # happened) or NEW (replace completed before kill). NEVER a
    # partial write of the new content. Tempfile orphan in the
    # parent dir is acceptable per the script docstring ("an OS-
    # level crash between flush and rename can still leave a `.tmp`
    # orphan").
    on_disk = target.read_text()
    assert on_disk in (_OLD_CONTENT, _NEW_CONTENT), (
        f"atomic-write smoke broken: on-disk content matches neither pre nor post state; "
        f"got {on_disk!r}"
    )
    # With the deterministic gate, the kill is guaranteed to land
    # BEFORE the real `os.replace` runs — the child blocks in
    # `hold_event.wait()` until SIGKILL terminates it. So the
    # expected outcome is OLD. Asserting it explicitly is what gives
    # the smoke test teeth — without this, an environment that
    # somehow bypassed the gate (kernel signal-delivery quirk) would
    # silently pass via the NEW branch.
    assert on_disk == _OLD_CONTENT, (
        f"kill landed too late: expected OLD content, got "
        f"{'NEW' if on_disk == _NEW_CONTENT else 'partial'}. "
        f"This indicates the SIGKILL didn't interrupt the os.replace path."
    )

    # File mode preserved across the (failed) write attempt.
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o640, f"expected 0o640 preserved, got {oct(mode)}"
    # Tempfile orphan tolerated (per docstring), but the live file
    # was never overwritten with partial content — that's what
    # matters.
