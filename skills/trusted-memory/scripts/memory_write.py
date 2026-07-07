"""Shared write primitives for the `tessl__trusted-memory` skill.

Two responsibilities:

1. `write_atomic` — tempfile → flush → fsync → chmod → os.replace.
   Single home for the recipe used by every memory-writer script.
   Caller-driven content; no parsing.

2. `dedup_filter` / `normalize_for_comparison` — whitespace-normalize
   candidates and filter out anything already present in an existing
   chunk of text. Caller picks the split granularity (line for daily
   logs, blank-line block for `daily_discoveries.md`). The helper is
   pure — it does not touch disk and does not lock — so the call site
   keeps full control of the read-modify-write cycle the file lock
   protects.

Why one module, not three: the deer-flow pattern in `jbaruch/nanoclaw#365`
calls for dedup at apply time alongside the atomic write. Two writers
in this skill (and a third coming for `daily_discoveries.md`) had
diverging private copies of the atomic-write helper; consolidating
here removes the drift surface and gives the new dedup logic a single
home its callers all reach the same way.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Callable

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_for_comparison(text: str) -> str:
    """Collapse runs of whitespace to a single space, normalize line
    endings, strip leading/trailing whitespace. Used to compare a
    candidate against existing entries for dedup purposes.

    Deliberately lossy: `"  - 09:00\tUTC —\n  hello\r\n"` and
    `"- 09:00 UTC — hello"` compare equal. That's the whole point —
    a reformatted-but-semantically-identical entry should be treated
    as a duplicate, otherwise dedup is defeated by trivial whitespace
    drift between writers.
    """
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    return _WHITESPACE_RUN.sub(" ", unified).strip()


def dedup_filter(
    existing: str,
    candidates: list[str],
    *,
    split: str = "\n",
    normalize: Callable[[str], str] = normalize_for_comparison,
) -> tuple[list[str], list[str]]:
    """Return `(kept, dropped)` from `candidates`.

    `existing` is the current file content (caller has already read
    it under whatever lock applies). It is split on `split` to derive
    the existing entry set. Each existing piece is normalized via
    `normalize`; empty pieces are ignored.

    A candidate is dropped when its normalized form matches any
    existing normalized piece, or when an earlier candidate in the
    same batch normalized to the same form (within-batch dedup so a
    caller passing the same entry twice doesn't land twice).

    `split="\\n"` — line-granularity, used by daily-log writers.
    `split="\\n\\n"` — blank-line block granularity, used by the
    daily-discoveries writer where each entry is a multi-line block
    (`## YYYY-MM-DD HH:MM UTC` + `**What:**` + `**Context:**` +
    `**Promote to:**`).

    `normalize` defaults to `normalize_for_comparison`. A caller whose
    entries carry per-write noise (e.g. a wall-clock timestamp line)
    passes a normalizer that strips the noise first, so the dedup key
    is the stable part of the entry. The normalizer must return "" for
    entries that are empty after stripping — those are surfaced as
    dropped, same as whitespace-only candidates.
    """
    existing_norms: set[str] = set()
    for piece in existing.split(split):
        norm = normalize(piece)
        if norm:
            existing_norms.add(norm)

    kept: list[str] = []
    dropped: list[str] = []
    seen_in_batch: set[str] = set()
    for candidate in candidates:
        norm = normalize(candidate)
        if not norm:
            # Empty / whitespace-only entries are not real entries;
            # surface them as dropped so the caller can fail loud
            # rather than silently writing blank lines.
            dropped.append(candidate)
            continue
        if norm in existing_norms or norm in seen_in_batch:
            dropped.append(candidate)
            continue
        seen_in_batch.add(norm)
        kept.append(candidate)
    return kept, dropped


def write_atomic(path: Path, content: str, *, default_mode: int = 0o644) -> None:
    """Atomically replace `path`'s contents with `content`.

    Tempfile in the same directory → write → flush → fsync → chmod
    (to the target's existing mode, or `default_mode` if creating
    fresh) → os.replace.

    Cleanup of the tempfile is best-effort on **handled** exceptions
    (IO failures the interpreter sees). An OS-level crash — SIGKILL,
    OOM, power loss — cannot run this handler and can still leave a
    `.<name>.<rand>.tmp` orphan next to the target. The target file
    itself is never partial: `os.replace` is atomic on POSIX and on
    Windows for same-volume renames.

    The chmod step preserves the file mode of an existing target —
    mkstemp defaults to 0600, which would silently narrow shared
    state files (`/workspace/group/*`, `/workspace/trusted/memory/*`)
    on the first overwrite without this step.

    Raises `OSError` on any handled IO failure; caller decides how to
    respond. The original exception is re-raised even if the cleanup
    itself hits a secondary `OSError` (the secondary is swallowed so
    diagnostics see the root cause, not the cleanup symptom).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        target_mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        target_mode = default_mode

    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    # `os.fdopen` takes ownership of the fd. If it raises before the
    # context manager can grab the file object (rare — invalid mode
    # or memory exhaustion), the raw fd is still ours to close so it
    # doesn't leak. `fdopened` tracks the handoff.
    fdopened = False
    try:
        f = os.fdopen(fd, "w", encoding="utf-8")
        fdopened = True
        try:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        finally:
            f.close()
        os.chmod(tmp, target_mode)
        os.replace(tmp, path)
    except OSError:
        if not fdopened:
            try:
                os.close(fd)
            except OSError:
                # Cleanup-of-cleanup: never let a secondary OSError
                # mask the original failure the caller needs to see.
                pass
        try:
            os.unlink(tmp)
        except OSError:
            # Same rule for the tempfile unlink: a non-FileNotFound
            # OSError here (EBUSY, EACCES, EIO) must not propagate
            # past the original write/chmod/replace failure.
            pass
        raise
