#!/usr/bin/env python3
"""Atomically append one or more lines to a daily memory log.

Replaces the LLM-driven `Read`/`Write` flow for the Rolling Memory
Updates section of `tessl__trusted-memory`. Multiple processes can
call this helper concurrently — default container during a turn,
maintenance container during a scheduled task, sub-skills mid-step —
and the contract is "everyone's lines land, nothing clobbers anyone
else's."

Per #275 (umbrella #412): the prior shape was the LLM reads the file,
appends in memory, writes the result. Concurrent reads from container
A and container B see the same baseline; whichever writes second
overwrites the first's append. Daily logs were silently losing entries
during overlap windows. This helper holds an `fcntl.LOCK_EX` on a
sibling `<daily-file>.lock` for the entire read-modify-write cycle so
the two writers serialize.

Usage:
    append-to-daily-log.py --target group|trusted
                           [--line "<text>" ...] [--lines-file <path>]
                           [--date YYYY-MM-DD]
                           [--group-daily <path>] [--trusted-daily <path>]

Behavior:
    - `--target group`   → /workspace/group/memory/daily/<UTC-today>.md
    - `--target trusted` → /workspace/trusted/memory/daily/<UTC-today>.md
    - `--group-daily` / `--trusted-daily` override the daily-dir for
      the corresponding target (alternate mount layouts, debugging,
      tests). Falls back to `NANOCLAW_GROUP_DAILY` /
      `NANOCLAW_TRUSTED_DAILY` env vars when the flag is omitted, then
      to the default constant. Flag wins over env wins over default.
    - `--date` overrides the resolved UTC date (test seam; production
      callers omit it and let the helper read the wall clock).
    - Lines come from `--line` (single, repeatable), `--lines-file`
      (one per newline), or stdin if neither flag is supplied. At
      least one non-empty line is required.
    - The helper does NOT prepend a `- ` bullet marker or assemble the
      `HH:MM UTC ...` prefix — the caller passes the fully-formed
      bullet text. This keeps the per-target format choice (group:
      `- HH:MM UTC — message` vs trusted: `- HH:MM UTC [chat] —
      message`) in the SKILL where the chat-name resolution happens.
    - If the target file is absent the helper creates it with a
      `# Daily Summary — YYYY-MM-DD\n\n` header (the canonical header
      the nightly archive pipeline recognises), then appends the lines.
    - Lines are appended at the END of the file regardless of their
      timestamp prefix. If the helper detects the new lines' first
      timestamp is BEFORE the existing file's last timestamp it logs
      a one-line stderr warning ("out-of-order") but still appends —
      cross-group writers and clock-skew retries can legitimately
      arrive late, and silent reorder would mask actual bugs.
    - Per `jbaruch/nanoclaw#365`: candidate lines are whitespace-
      normalized (via `memory_write.normalize_for_comparison`) and
      compared against the existing file's normalized lines. Lines
      whose normalized form already appears in the file — or that
      duplicate an earlier line in the same batch — are skipped at
      write time. All-duplicates is a valid no-op (rc 0, no write,
      `appended_lines: 0`). Existing on-disk lines are NEVER touched
      — dedup applies only to new appends.

Output (stdout, single-line JSON):
    {
      "path": "<resolved daily-file path>",
      "appended_lines": <int>,            # kept after dedup
      "dropped_duplicates": <int>,        # filtered as duplicates
      "final_line_count": <int>,
      "created": <bool>,
      "out_of_order": <bool>
    }

Exit codes:
    0  success (including all-duplicates no-op)
    1  IO failure (lock acquisition / read / write)
    2  usage / validation error (no lines, bad --target, bad --date,
       both --line and --lines-file with conflicting content)

Atomic write: delegated to `memory_write.write_atomic` (tempfile →
flush → fsync → chmod → os.replace, preserving file mode across
overwrites). Tempfile cleanup is best-effort on handled OSError; an
OS-level crash (SIGKILL, OOM) between flush and rename can still
leave a `.<name>.tmp` orphan that the next call would overwrite,
since `mkstemp` regenerates the suffix per call.

Lock file: `<daily-file>.lock` is created on demand and never removed
— per-day file leaks ~0.1 KiB per group per day, far below worth
cleaning up, and removing the lock file mid-session would race with
concurrent acquisitions.
"""

import argparse
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# `memory_write` is a sibling module in the same `scripts/` directory.
# Loading the script by its kebab-case filename via importlib doesn't
# put that directory on sys.path the way a normal `python foo.py` run
# does, so add it explicitly before the import — the in-process tests
# rely on this and so does the production CLI invocation.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from memory_write import dedup_filter, write_atomic  # noqa: E402

GROUP_DAILY_DIR = "/workspace/group/memory/daily"
TRUSTED_DAILY_DIR = "/workspace/trusted/memory/daily"
# `# Daily Summary — YYYY-MM-DD` is the canonical header the nightly
# archive pipeline recognises. The helper that creates daily files
# must produce this exact header — otherwise the archiver would skip
# these files and they'd accumulate forever in `daily/`. Em dash is
# U+2014.
DAILY_HEADER_TEMPLATE = "# Daily Summary — {date}\n\n"
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Match a leading `- HH:MM UTC` (with optional `[chat-name]` between
# the timestamp and the message body) so we can compare new vs.
# existing entries for the out-of-order warning. Mirrors the format
# the trusted-memory SKILL.md prescribes; non-matching lines are
# accepted but skipped for the comparison.
TIMESTAMP_PREFIX_RE = re.compile(r"^-\s+(\d{2}):(\d{2})\s+UTC\b")


def _resolve_target_dir(target: str, args) -> str:
    """Resolve the daily-dir for `--target`. Override precedence:
    explicit `--group-daily` / `--trusted-daily` flag → matching env var
    (`NANOCLAW_GROUP_DAILY` / `NANOCLAW_TRUSTED_DAILY`) → module-level
    default constant. Container deployments that mount the memory tree
    somewhere other than `/workspace/{group,trusted}/memory/daily` use
    the env vars; tests use the flags or monkeypatch the constants."""
    if target == "group":
        if args is not None and getattr(args, "group_daily", None):
            return args.group_daily
        return os.environ.get("NANOCLAW_GROUP_DAILY") or GROUP_DAILY_DIR
    if target == "trusted":
        if args is not None and getattr(args, "trusted_daily", None):
            return args.trusted_daily
        return os.environ.get("NANOCLAW_TRUSTED_DAILY") or TRUSTED_DAILY_DIR
    raise ValueError(f"unknown --target {target!r}; expected 'group' or 'trusted'")


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _last_timestamp(content: str) -> Optional[int]:
    """Return minutes-since-midnight for the last `- HH:MM UTC ...`
    line in the file, or None if no such line exists. Used only for
    the out-of-order warning."""
    last: Optional[int] = None
    for line in content.splitlines():
        m = TIMESTAMP_PREFIX_RE.match(line)
        if m:
            last = int(m.group(1)) * 60 + int(m.group(2))
    return last


def _first_timestamp(lines: List[str]) -> Optional[int]:
    for line in lines:
        m = TIMESTAMP_PREFIX_RE.match(line)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
    return None


def _collect_lines(args, parser) -> List[str]:
    """Resolve `--line`, `--lines-file`, or stdin into the final list.
    Validates non-empty result. Lines are stripped of trailing
    newlines but otherwise unchanged (caller's whitespace is
    preserved).

    Source precedence: `--line` > `--lines-file` > stdin. The two
    flags are mutually exclusive (error). When a flag is supplied,
    stdin is ignored even if piped — that asymmetry is deliberate
    so a CI runner that always pipes empty stdin doesn't make the
    flagged invocation ambiguous, but `--line` and `--lines-file`
    being simultaneously set is genuinely ambiguous and worth an
    error."""
    if args.line and args.lines_file:
        parser.error("specify --line OR --lines-file, not both (mixing is ambiguous)")

    if args.lines_file:
        try:
            raw = Path(args.lines_file).read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(
                f"cannot read --lines-file {args.lines_file!r}: " f"{type(exc).__name__}: {exc}"
            )
            raise  # unreachable: parser.error() exits; makes the abort explicit to the type checker
        lines = [ln for ln in raw.splitlines() if ln.strip()]
    elif args.line:
        # `--line` is `action="append"` so it's already a list.
        lines = [ln for ln in args.line if ln.strip()]
    else:
        raw = sys.stdin.read()
        lines = [ln for ln in raw.splitlines() if ln.strip()]

    if not lines:
        parser.error(
            "no lines to append — pass --line, --lines-file, or pipe non-empty " "content on stdin"
        )
    return lines


def _append(*, daily_file: Path, lines: List[str]) -> dict:
    """Read existing content (or initialize header), filter out lines
    that duplicate an existing entry (whitespace-normalized match),
    append the survivors, atomic-write back. Caller MUST hold LOCK_EX
    before calling.

    Returns the JSON-serializable result dict. When every candidate
    line is already present the file is left untouched: no atomic
    write fires, `created=False`, `appended_lines=0`,
    `dropped_duplicates=len(lines)`. That keeps idempotent retries
    cheap and prevents an empty atomic-write churn cycle from
    bumping mtime/inode on a file that didn't actually change.
    """
    if daily_file.exists():
        existing = daily_file.read_text(encoding="utf-8")
        created = False
    else:
        existing = DAILY_HEADER_TEMPLATE.format(date=daily_file.stem)
        created = True

    kept, dropped = dedup_filter(existing, lines, split="\n")
    dropped_count = len(dropped)

    if not kept:
        # All candidate lines were already present (or the batch
        # collapsed to zero after within-batch dedup). Don't bump
        # mtime / inode on a no-change call; just report the outcome.
        # `created=False` even when the file didn't pre-exist, because
        # we haven't actually written it — the would-be header text
        # in `existing` is in-memory only.
        final_line_count = existing.count("\n") if daily_file.exists() else 0
        return {
            "path": str(daily_file),
            "appended_lines": 0,
            "dropped_duplicates": dropped_count,
            "final_line_count": final_line_count,
            "created": False,
            "out_of_order": False,
        }

    last_ts = _last_timestamp(existing)
    first_new_ts = _first_timestamp(kept)
    out_of_order = last_ts is not None and first_new_ts is not None and first_new_ts < last_ts

    # Ensure exactly one blank line before the appended block, and a
    # single trailing newline. existing-file callers normally already
    # end in `\n`; tolerate the absence.
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    new_content = existing + "\n".join(kept) + "\n"

    write_atomic(daily_file, new_content)

    final_line_count = new_content.count("\n")
    return {
        "path": str(daily_file),
        "appended_lines": len(kept),
        "dropped_duplicates": dropped_count,
        "final_line_count": final_line_count,
        "created": created,
        "out_of_order": out_of_order,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target", required=True, choices=("group", "trusted"))
    parser.add_argument("--line", action="append", default=[], help="bullet line; repeatable")
    parser.add_argument("--lines-file", help="path to a file of newline-separated lines")
    parser.add_argument(
        "--date",
        help="UTC YYYY-MM-DD override (test seam); defaults to today UTC",
    )
    parser.add_argument(
        "--group-daily",
        help=(
            "override the group daily-dir (default /workspace/group/memory/daily). "
            "Falls back to NANOCLAW_GROUP_DAILY env var, then the default."
        ),
    )
    parser.add_argument(
        "--trusted-daily",
        help=(
            "override the trusted daily-dir (default /workspace/trusted/memory/daily). "
            "Falls back to NANOCLAW_TRUSTED_DAILY env var, then the default."
        ),
    )
    args = parser.parse_args(argv)

    if args.date is not None and not ISO_DATE_RE.match(args.date):
        parser.error(f"--date {args.date!r} must be YYYY-MM-DD (ISO-8601 calendar date)")

    try:
        target_dir = _resolve_target_dir(args.target, args)
    except ValueError as exc:
        parser.error(str(exc))
        return 2  # parser.error exits 2; this is for type-checkers

    date_str = args.date or _today_utc()
    daily_file = Path(target_dir) / f"{date_str}.md"
    lock_path = Path(str(daily_file) + ".lock")

    lines = _collect_lines(args, parser)

    # Open the lock file before acquiring LOCK_EX. `a+` creates the
    # lock file if absent without truncating; we never read or write
    # its content, only hold the OS-level advisory lock on it.
    try:
        daily_file.parent.mkdir(parents=True, exist_ok=True)
        lock_f = open(lock_path, "a+")
    except OSError as exc:
        sys.stderr.write(
            f"append-to-daily-log: cannot open lock file {lock_path}: "
            f"{type(exc).__name__}: {exc}\n"
        )
        return 1

    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            sys.stderr.write(
                f"append-to-daily-log: cannot acquire LOCK_EX on {lock_path}: "
                f"{type(exc).__name__}: {exc}\n"
            )
            return 1

        try:
            result = _append(daily_file=daily_file, lines=lines)
        except OSError as exc:
            sys.stderr.write(
                f"append-to-daily-log: IO failed for {daily_file}: "
                f"{type(exc).__name__}: {exc}\n"
            )
            return 1
    finally:
        # Closing the fd releases the flock; no explicit LOCK_UN needed.
        lock_f.close()

    if result["out_of_order"]:
        sys.stderr.write(
            f"append-to-daily-log: out-of-order append on {daily_file} — "
            f"new entry's timestamp precedes the file's last timestamp. "
            f"Likely a cross-group writer or a clock-skew retry; the line "
            f"is appended at end-of-file regardless.\n"
        )

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
