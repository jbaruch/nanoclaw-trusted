#!/usr/bin/env python3
"""Append entries to a daily memory log under an advisory lock.

Replaces the LLM-driven `read → modify → Write` flow that was racy
when multiple containers (default + maintenance + sub-skills) appended
to the same daily file simultaneously: container A's read + container
B's write between A's read and write meant A's append silently
overwrote B's. See jbaruch/nanoclaw#275 for the breaking shape.

Usage:
    append-to-daily-log.py --target group   --line "<entry>"
    append-to-daily-log.py --target trusted --line "<entry>"
    append-to-daily-log.py --target group   --lines-file path/to/lines.txt
    append-to-daily-log.py --target group   --line "..." --date 2026-04-29

`--target group`   → `/workspace/group/memory/daily/<UTC-date>.md`
`--target trusted` → `/workspace/trusted/memory/daily/<UTC-date>.md`

Override defaults with `--group-daily` / `--trusted-daily` (or env vars
`NANOCLAW_GROUP_DAILY` / `NANOCLAW_TRUSTED_DAILY`) — used by tests, but
intentional for any container that mounts the memory tree elsewhere.

Locking: `fcntl.LOCK_EX` on `<daily-file>.lock` for the duration of the
read-modify-write cycle. The lock file is per-day so two containers
appending to the same date serialise; appends to *different* dates
proceed in parallel.

Header: if the daily file does not exist, the helper creates it with
`# Daily Summary — YYYY-MM-DD` — the format already produced by other
writers and consumed by `archive-helper.py`'s daily-header regex.

Output: single-line JSON on stdout per `script-delegation`:
    {"path": "...", "appended_lines": N, "final_line_count": M,
     "monotonic": true|false}

`monotonic: false` means at least one new line's `HH:MM UTC` prefix is
earlier than the last existing entry's. The append still happens — a
slight clock skew between containers is normal — but the flag lets
callers surface it (or callers ignore it when they're appending a
batch with intentional ordering, e.g. backfill).

Exit codes (per file-hygiene + script-delegation):
    0 — success (append completed, JSON on stdout)
    2 — hard error (filesystem failure, malformed CLI input);
        diagnostic on stderr; stdout left clean of partial JSON
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_GROUP_DAILY = "/workspace/group/memory/daily"
DEFAULT_TRUSTED_DAILY = "/workspace/trusted/memory/daily"

# Daily file header — matches the documented format in
# `nanoclaw-admin/skills/nightly-housekeeping/SKILL.md` and the
# `archive-helper.py` daily-header regex. Em dash is U+2014.
DAILY_HEADER_TEMPLATE = "# Daily Summary — {date}\n"

# Bullet entries written by trusted-memory and heartbeat use
# `- HH:MM UTC ...`. We extract the prefix to check non-decreasing
# ordering — `re.match` not `re.fullmatch` so the rest of the line
# (the message body) is free-form.
ENTRY_PREFIX_RE = re.compile(r"^- (\d{2}):(\d{2}) UTC\b")


def resolve_daily_dir(target: str, args: argparse.Namespace) -> Path:
    if target == "group":
        override = args.group_daily or os.environ.get("NANOCLAW_GROUP_DAILY")
        return Path(override or DEFAULT_GROUP_DAILY)
    if target == "trusted":
        override = args.trusted_daily or os.environ.get("NANOCLAW_TRUSTED_DAILY")
        return Path(override or DEFAULT_TRUSTED_DAILY)
    raise ValueError(f"unknown target {target!r}")


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def parse_date(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def atomic_write_text(path: Path, content: str, default_mode: int = 0o644) -> None:
    """Atomic replace, preserving the target's existing permissions.

    Lifted in shape from `register-session.py::atomic_write_text` so
    the two helpers behave identically under concurrency. Tempfile
    lives in the same directory as the target so the final
    `os.replace` is on the same filesystem (cross-FS rename would
    fall back to copy and lose atomicity).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        target_mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        target_mode = default_mode

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=str(path.parent),
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
            encoding="utf-8",
        ) as tf:
            tmp_path = tf.name
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())
        os.chmod(tmp_path, target_mode)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def last_entry_minutes(existing: str) -> Optional[int]:
    """Return the `HH*60+MM` of the last `- HH:MM UTC` bullet in the
    file, or None if no such entry exists. Iterates from the END so
    long daily logs short-circuit on the first match instead of
    scanning the whole file."""
    for line in reversed(existing.splitlines()):
        m = ENTRY_PREFIX_RE.match(line)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
    return None


def min_entry_minutes(lines: list[str]) -> Optional[int]:
    """Smallest `HH*60+MM` across all bullet lines in the input batch.

    Used for the monotonic check: a batch is non-monotonic if ANY
    of its entries is earlier than the existing tail, not just the
    first one. The earlier `first_entry_minutes` only checked the
    first matching line, so a `[09:00, 02:54]` batch appended after
    `08:00` would have been reported `monotonic: true`.
    """
    earliest: Optional[int] = None
    for line in lines:
        m = ENTRY_PREFIX_RE.match(line)
        if m:
            mins = int(m.group(1)) * 60 + int(m.group(2))
            if earliest is None or mins < earliest:
                earliest = mins
    return earliest


def line_count(text: str) -> int:
    """Length-in-lines of `text`. Uses `splitlines()` so a final line
    without a trailing newline still counts — `text.count("\\n")`
    would undercount by one in that (rare but legal) shape."""
    return len(text.splitlines())


def append_lines(daily_file: Path, new_lines: list[str], date: dt.date) -> dict:
    if not new_lines:
        # No-op append still reports current state so the caller can
        # log a deterministic outcome — exit 0 with appended=0.
        existing = daily_file.read_text(encoding="utf-8") if daily_file.exists() else ""
        return {
            "path": str(daily_file),
            "appended_lines": 0,
            "final_line_count": line_count(existing),
            "monotonic": True,
        }

    if daily_file.exists():
        existing = daily_file.read_text(encoding="utf-8")
        prior_last = last_entry_minutes(existing)
    else:
        existing = DAILY_HEADER_TEMPLATE.format(date=date.strftime("%Y-%m-%d"))
        prior_last = None

    earliest_new = min_entry_minutes(new_lines)
    monotonic = True
    if prior_last is not None and earliest_new is not None and earliest_new < prior_last:
        monotonic = False

    # Ensure the existing content ends with exactly one newline before
    # appending — header-only files already do, but a manually edited
    # file might not.
    if existing and not existing.endswith("\n"):
        existing = existing + "\n"

    appended_block = "\n".join(new_lines)
    if not appended_block.endswith("\n"):
        appended_block = appended_block + "\n"
    new_content = existing + appended_block

    atomic_write_text(daily_file, new_content)

    return {
        "path": str(daily_file),
        "appended_lines": len(new_lines),
        "final_line_count": line_count(new_content),
        "monotonic": monotonic,
    }


def acquire_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+")
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    return f


def read_lines_input(args: argparse.Namespace) -> list[str]:
    if args.line is not None:
        return [args.line.rstrip("\n")]
    if args.lines_file is not None:
        text = Path(args.lines_file).read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if ln.strip()]
    raise SystemExit("append-to-daily-log: --line or --lines-file required")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target",
        required=True,
        choices=("group", "trusted"),
        help="Which daily-log tree to write into.",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--line", help="A single entry to append (verbatim).")
    src.add_argument(
        "--lines-file",
        help="Path to a UTF-8 text file; each non-blank line is appended.",
    )
    parser.add_argument(
        "--date",
        help="UTC date YYYY-MM-DD (default: today UTC).",
    )
    parser.add_argument("--group-daily", help="Override group daily dir.")
    parser.add_argument("--trusted-daily", help="Override trusted daily dir.")

    args = parser.parse_args()

    try:
        date = parse_date(args.date) if args.date else utc_today()
    except ValueError as exc:
        parser.error(f"invalid --date {args.date!r}: {exc} (expected YYYY-MM-DD)")

    try:
        daily_dir = resolve_daily_dir(args.target, args)
    except ValueError as exc:
        parser.error(str(exc))

    daily_file = daily_dir / f"{date.strftime('%Y-%m-%d')}.md"
    lock_path = Path(f"{daily_file}.lock")

    try:
        new_lines = read_lines_input(args)
    except OSError as exc:
        sys.stderr.write(f"append-to-daily-log: cannot read --lines-file: {exc}\n")
        sys.exit(2)
    except UnicodeDecodeError as exc:
        # Caught alongside OSError: a non-UTF-8 --lines-file would
        # otherwise crash with a traceback + rc=1, violating the
        # "exit 2 on hard error / stdout clean" contract.
        sys.stderr.write(
            f"append-to-daily-log: --lines-file is not valid UTF-8: {exc}\n"
        )
        sys.exit(2)

    try:
        lock_f = acquire_lock(lock_path)
    except OSError as exc:
        sys.stderr.write(f"append-to-daily-log: cannot acquire lock {lock_path}: {exc}\n")
        sys.exit(2)

    try:
        try:
            result = append_lines(daily_file, new_lines, date)
        except UnicodeDecodeError as exc:
            # Same contract guard for the daily file: a manually-edited
            # daily with non-UTF-8 bytes shouldn't traceback out.
            sys.stderr.write(
                f"append-to-daily-log: existing daily file {daily_file} is "
                f"not valid UTF-8: {exc}\n"
            )
            sys.exit(2)
        except OSError as exc:
            sys.stderr.write(f"append-to-daily-log: write failed for {daily_file}: {exc}\n")
            sys.exit(2)
    finally:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_f.close()

    if not result["monotonic"]:
        sys.stderr.write(
            f"append-to-daily-log: non-monotonic append to {daily_file} — "
            f"new entry's HH:MM is earlier than the existing tail "
            f"(clock skew between containers is normal; flagged for caller).\n"
        )

    sys.stdout.write(json.dumps(result) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
