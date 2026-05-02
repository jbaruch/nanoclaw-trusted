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
    append-to-daily-log.py --target group|trusted [--line "<text>"]
                           [--lines-file <path>] [--date YYYY-MM-DD]

Behavior:
    - `--target group`   → /workspace/group/memory/daily/<UTC-today>.md
    - `--target trusted` → /workspace/trusted/memory/daily/<UTC-today>.md
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
      `# Daily Summary — YYYY-MM-DD\n\n` header (matches the regex
      consumed by `nanoclaw-admin/skills/nightly-housekeeping/scripts/
      archive-helper.py:57` so files are picked up by nightly archival),
      then appends the lines.
    - Lines are appended at the END of the file regardless of their
      timestamp prefix. If the helper detects the new lines' first
      timestamp is BEFORE the existing file's last timestamp it logs
      a one-line stderr warning ("out-of-order") but still appends —
      cross-group writers and clock-skew retries can legitimately
      arrive late, and silent reorder would mask actual bugs.

Output (stdout, single-line JSON):
    {
      "path": "<resolved daily-file path>",
      "appended_lines": <int>,
      "final_line_count": <int>,
      "created": <bool>,
      "out_of_order": <bool>
    }

Exit codes:
    0  success
    1  IO failure (lock acquisition / read / write)
    2  usage / validation error (no lines, bad --target, bad --date,
       both --line and --lines-file with conflicting content)

Atomic write: tempfile in same directory → flush → fsync → os.replace,
matching `register-session.atomic_write_text` so file mode is
preserved across overwrites. Tempfile cleanup is best-effort on
handled OSError; an OS-level crash (SIGKILL, OOM) between flush and
rename can still leave a `.<name>.tmp` orphan that the next call
would overwrite, since `mkstemp` regenerates the suffix per call.

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
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

GROUP_DAILY_DIR = "/workspace/group/memory/daily"
TRUSTED_DAILY_DIR = "/workspace/trusted/memory/daily"
# `# Daily Summary — YYYY-MM-DD` is the canonical header — matches
# the regex in `nanoclaw-admin/skills/nightly-housekeeping/scripts/
# archive-helper.py:57` AND the example header in `append-daily-
# summary.py`'s docstring. The trusted-tile and admin-tile daily
# files share the same archive pipeline, so the helper that creates
# them must produce a header the archiver recognises — otherwise
# `archive-helper.py archive-daily` would skip these files and they'd
# accumulate forever in `daily/`. Em dash is U+2014.
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


def atomic_write_text(path: Path, content: str, default_mode: int = 0o644) -> None:
    """Tempfile + fsync + os.replace, preserving the existing file
    mode when overwriting. Caller handles OSError; this function only
    cleans up the tempfile on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        target_mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        target_mode = default_mode

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, target_mode)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


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
    """Read existing content (or initialize header), append the new
    lines, atomic-write back. Caller MUST hold LOCK_EX before calling.
    Returns the JSON-serializable result dict."""
    if daily_file.exists():
        existing = daily_file.read_text(encoding="utf-8")
        created = False
    else:
        existing = DAILY_HEADER_TEMPLATE.format(date=daily_file.stem)
        created = True

    last_ts = _last_timestamp(existing)
    first_new_ts = _first_timestamp(lines)
    out_of_order = last_ts is not None and first_new_ts is not None and first_new_ts < last_ts

    # Ensure exactly one blank line before the appended block, and a
    # single trailing newline. existing-file callers normally already
    # end in `\n`; tolerate the absence.
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    new_content = existing + "\n".join(lines) + "\n"

    atomic_write_text(daily_file, new_content)

    final_line_count = new_content.count("\n")
    return {
        "path": str(daily_file),
        "appended_lines": len(lines),
        "final_line_count": final_line_count,
        "created": created,
        "out_of_order": out_of_order,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
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
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
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
