#!/usr/bin/env python3
"""Atomically append a block-format entry to `daily_discoveries.md`.

The `daily-discoveries-rule` prescribes a four-line block per entry:

    ## YYYY-MM-DD HH:MM UTC
    **What:** <one-line description>
    **Context:** <how you found out>
    **Promote to:** <RUNBOOK.md / typed memory file + MEMORY.md / unsure>

Before this script, the agent wrote the block via Read/Write of the
target file. Concurrent containers (default + maintenance + sub-skill
spawn) raced the read-modify-write cycle, and the agent never deduped,
so the same fact got re-logged on every retry. Per `jbaruch/nanoclaw
#365` this helper closes both gaps: a per-file `fcntl.LOCK_EX` lock
serializes writers, and the candidate block is dedup-filtered against
the file's existing blocks (split on blank lines, whitespace-
normalized, `## <timestamp>` header line ignored) so retries are
idempotent even when the retry lands on a later wall-clock minute.

Usage:
    append-daily-discovery.py
        --what "<what was learned>"
        --context "<how/why>"
        --promote-to "<RUNBOOK.md | typed-memory + MEMORY.md | unsure>"
        [--timestamp "YYYY-MM-DD HH:MM UTC"]     # test seam
        [--discoveries-file <path>]              # override default

Behavior:
    - Default target is `/workspace/trusted/memory/daily_discoveries.md`.
      Override with `--discoveries-file` or `NANOCLAW_DISCOVERIES_FILE`
      env var (flag wins over env wins over default).
    - `--timestamp` overrides the resolved UTC timestamp (test seam);
      production callers omit it and let the helper read the wall clock.
    - If the target file is absent it's created with a
      `# Daily Discoveries\n\n` header before the first block is
      appended.
    - The candidate block is whitespace-normalized with its
      `## <timestamp>` header line stripped, then compared to every
      existing block in the file (blocks delimited by blank lines,
      normalized the same way). The timestamp is excluded from the
      dedup key on purpose: a retry of the same discovery carries a
      fresh wall-clock stamp, and a timestamp-sensitive key would
      defeat the retry idempotency this script exists to provide.
      If the candidate matches an existing block — or normalizes to
      empty — the write is skipped; the file is not touched at all
      (no mtime / inode bump) and the script exits 0 with
      `appended: false`.

Output (stdout, single-line JSON):
    {
      "path": "<resolved file path>",
      "appended": <bool>,                # true on write, false on dup
      "dropped_duplicate": <bool>,       # true iff dedup blocked write
      "created": <bool>,                 # file was created this call
      "timestamp": "<YYYY-MM-DD HH:MM UTC>" | null
    }

    `timestamp` carries the stamp baked into the appended block when
    `appended` is true. On the dedup-skip path it is `null` — the
    candidate block matches an existing entry whose timestamp is
    already on disk, so the new stamp was never persisted and the
    caller should treat it as "no new entry for this call".

Exit codes:
    0  success (including dedup-skip)
    1  IO failure (lock acquisition / read / write)
    2  usage / validation error (missing / empty / multiline
       --what / --context / --promote-to, bad --timestamp format)

Atomic write delegated to `memory_write.write_atomic`. Lock file
`<discoveries-file>.lock` is created on demand and never removed —
~0.1 KiB of forever-leak per workspace, same trade-off as the daily-
log appender.
"""

import argparse
import fcntl
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Sibling `memory_write` module — see `append-to-daily-log.py`'s
# matching block for the sys.path rationale.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from memory_write import dedup_filter, normalize_for_comparison, write_atomic  # noqa: E402

DEFAULT_DISCOVERIES_FILE = "/workspace/trusted/memory/daily_discoveries.md"
ENV_OVERRIDE = "NANOCLAW_DISCOVERIES_FILE"
FILE_HEADER = "# Daily Discoveries\n\n"
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")


def _now_utc_stamp() -> str:
    """Match the on-disk shape `YYYY-MM-DD HH:MM UTC` from
    `daily-discoveries-rule.md`."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _resolve_target_path(args) -> Path:
    """`--discoveries-file` > `NANOCLAW_DISCOVERIES_FILE` env > default."""
    import os

    if getattr(args, "discoveries_file", None):
        return Path(args.discoveries_file)
    return Path(os.environ.get(ENV_OVERRIDE) or DEFAULT_DISCOVERIES_FILE)


def _format_block(timestamp: str, what: str, context: str, promote_to: str) -> str:
    return (
        f"## {timestamp}\n"
        f"**What:** {what}\n"
        f"**Context:** {context}\n"
        f"**Promote to:** {promote_to}\n"
    )


_TS_HEADER_RE = re.compile(r"^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\s*$")


def _normalize_ignoring_timestamp(block: str) -> str:
    """Dedup key for a discovery block: the whitespace-normalized body
    with the `## <timestamp>` header line stripped. A retry carries a
    fresh wall-clock stamp; keying on the timestamp would re-append
    the same discovery on every retry."""
    unified = block.replace("\r\n", "\n").replace("\r", "\n")
    body = [line for line in unified.split("\n") if not _TS_HEADER_RE.match(line)]
    return normalize_for_comparison("\n".join(body))


def _append(*, target: Path, block: str) -> dict:
    """Read existing content (or initialize header), filter the block
    against existing blocks, atomic-write back if not a duplicate.
    Caller MUST hold LOCK_EX before calling."""
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        created = False
    else:
        existing = FILE_HEADER
        created = True

    kept, dropped = dedup_filter(
        existing, [block], split="\n\n", normalize=_normalize_ignoring_timestamp
    )

    if not kept:
        # Duplicate (or the candidate normalized to empty, which
        # shouldn't happen given upstream validation but we belt-and-
        # braces it). Leave the file untouched.
        return {
            "path": str(target),
            "appended": False,
            "dropped_duplicate": bool(dropped),
            "created": False,
            "timestamp": None,
        }

    # Ensure a blank line precedes the appended block when the file
    # has prior content. The header already ends with `\n\n`, but a
    # legacy file written without a header might end with a single
    # `\n` — normalize.
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing.endswith("\n") and not existing.endswith("\n\n"):
        existing += "\n"
    new_content = existing + kept[0]
    if not new_content.endswith("\n"):
        new_content += "\n"

    write_atomic(target, new_content)
    return {
        "path": str(target),
        "appended": True,
        "dropped_duplicate": False,
        "created": created,
        "timestamp": None,  # caller fills in
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--what", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--promote-to", required=True, dest="promote_to")
    parser.add_argument(
        "--timestamp",
        help="UTC `YYYY-MM-DD HH:MM UTC` override (test seam); defaults to now UTC",
    )
    parser.add_argument(
        "--discoveries-file",
        dest="discoveries_file",
        help=(
            f"override the discoveries file path (default {DEFAULT_DISCOVERIES_FILE}). "
            f"Falls back to {ENV_OVERRIDE} env var, then the default."
        ),
    )
    args = parser.parse_args(argv)

    if args.timestamp is not None and not TIMESTAMP_RE.match(args.timestamp):
        parser.error(
            f"--timestamp {args.timestamp!r} must match `YYYY-MM-DD HH:MM UTC`"
        )

    # Cheap validation: empty or whitespace-only field would produce
    # a useless `**What:** ` block; reject early so the operator sees
    # a usage error rather than an empty entry on disk. CR/LF is
    # rejected because the block format is line-oriented — an embedded
    # newline lets a field value smuggle extra Markdown structure
    # (e.g. a fake `## <timestamp>` header or `**What:**` marker) into
    # the discoveries file, which is later loaded as trusted memory.
    for label, value in (("what", args.what), ("context", args.context), ("promote-to", args.promote_to)):
        if not value.strip():
            parser.error(f"--{label} must be non-empty")
        if "\r" in value or "\n" in value:
            parser.error(f"--{label} must be a single line (no CR/LF characters)")

    timestamp = args.timestamp or _now_utc_stamp()
    target = _resolve_target_path(args)
    lock_path = Path(str(target) + ".lock")
    block = _format_block(timestamp, args.what.strip(), args.context.strip(), args.promote_to.strip())

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_f = open(lock_path, "a+")
    except OSError as exc:
        sys.stderr.write(
            f"append-daily-discovery: cannot open lock file {lock_path}: "
            f"{type(exc).__name__}: {exc}\n"
            f"  fix: verify {target.parent} exists and is writable for "
            f"this process; if the canonical mount is unavailable, "
            f"override with --discoveries-file <path> or set the "
            f"{ENV_OVERRIDE} env var to a writable path.\n"
        )
        return 1

    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            sys.stderr.write(
                f"append-daily-discovery: cannot acquire LOCK_EX on {lock_path}: "
                f"{type(exc).__name__}: {exc}\n"
                f"  fix: another writer is likely holding the lock; retry in a "
                f"few seconds. If the lock file is stale (no process holds it), "
                f"removing it is safe — concurrent acquisitions race the recreate.\n"
            )
            return 1

        try:
            result = _append(target=target, block=block)
        except OSError as exc:
            sys.stderr.write(
                f"append-daily-discovery: IO failed for {target}: "
                f"{type(exc).__name__}: {exc}\n"
                f"  fix: check disk space and that {target.parent} is writable "
                f"for this process. If the canonical mount is unavailable, "
                f"override with --discoveries-file <path> or set the "
                f"{ENV_OVERRIDE} env var to a writable path.\n"
            )
            return 1
    finally:
        # Closing the fd releases the flock; no explicit LOCK_UN needed.
        lock_f.close()

    result["timestamp"] = timestamp if result["appended"] else None
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
