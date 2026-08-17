#!/usr/bin/env python3
"""Migrate the owner profile's canonical `## Addresses` block to the current schema.

The block is owner-state this skill writes and the travel tile reads
(`skills/trusted-memory/state-schema.md`). Per
`jbaruch/coding-policy: stateful-artifacts`, only the owner migrates it, and it
migrates on READ rather than whenever someone happens to edit the profile — a
block that sits at an old version until the next unrelated edit is a block that
sits at an old version indefinitely.

The transformation is fixed: restamp `- schema_version:` to `CURRENT_SCHEMA_VERSION`,
touch no other line. No key is added — `home_metro` (v2) has no default; it stays
absent until the operator names a metro, and absent means the travel tile treats
no trip as local. That is why the bump is additive and a reader accepting the new
version reads an old block unchanged.

Deterministic parse + rewrite of a fixed block, so it is a script and not agent
judgment (`jbaruch/coding-policy: script-delegation`). Idempotent: a block
already at the current version is left byte-identical and reported
`migrated: false`, so the bootstrap step can run it every session.

ORDERING. Stamping a version readers do not yet accept makes the block read as
"no usable prior state" everywhere. Every reader accepting `CURRENT_SCHEMA_VERSION`
must be deployed first — see the state-schema's Schema versioning section.

Usage:
    migrate-addresses-block.py [--profile <path>]

Reads:
    - `--profile`, else `$USER_PROFILE_PATH`, else `/workspace/trusted/user_profile.md`

Writes:
    - the same file, atomically, ONLY when the stamp changes

Stdout (single-line JSON per `script-delegation`):
    {"migrated": <bool>, "from": <int|null>, "to": <int>, "path": "<path>"}
    `from` is the version found: an int, or null for the legacy pre-versioned
    block that carries no `schema_version` line at all.

Exit:
    0 — block is at the current version (migrated false) or was migrated
    1 — profile missing/unreadable, no `## Addresses` block, the block carries
        an unreadable or future `schema_version`, or a block due to be stamped
        is missing a `REQUIRED_KEYS` entry. Each writes an actionable stderr
        diagnostic; nothing is rewritten.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# E402: the sibling helper is only importable after the sys.path insert above,
# which must run before this import.
from memory_write import write_atomic  # noqa: E402

DEFAULT_PROFILE_PATH = "/workspace/trusted/user_profile.md"
PROFILE_PATH_ENV = "USER_PROFILE_PATH"

# The block shape this skill writes. Bump alongside the state-schema's
# `### vN → vN+1` section, and only once every reader accepting it is deployed.
CURRENT_SCHEMA_VERSION = 2

# Keys a block must carry before this script will stamp it current. Stamping a
# block that lacks them would publish a record claiming the current shape while
# missing it — readers would then take their "block is present and readable"
# path and find nothing, which is worse than the honest old stamp.
# `new_home_wip` is deliberately NOT required: it names a house under
# construction and legitimately disappears once that home is occupied and its
# value moves to `current_home`. `home_metro` is optional by definition.
REQUIRED_KEYS = ("current_home", "home_airport")

_ADDRESSES_HEADING_RE = re.compile(r"^[ \t]*##[ \t]+Addresses[ \t]*$", re.MULTILINE)
_NEXT_H2_RE = re.compile(r"^[ \t]*##[ \t]+\S", re.MULTILINE)
_SCHEMA_LINE_RE = re.compile(
    r"^(?P<prefix>\s*-\s*schema_version\s*:\s*)(?P<value>\S.*?)(?P<trailing>\s*)$",
    re.MULTILINE,
)
# The block's own provenance comment carries the version in prose. It moves with
# the stamp so the two never disagree — a comment claiming v1 above a v2 stamp is
# the kind of drift that sends the next reader to the wrong section of the docs.
_COMMENT_VERSION_RE = re.compile(r"(?P<prefix><!--[^>]*?schema[ \t]+v)(?P<value>\d+)")


def _block_bounds(text: str) -> tuple[int, int] | None:
    """(start, end) offsets of the `## Addresses` body, or None when absent.

    Body runs from just after the heading line to the next `## ` heading (or end
    of file), matching the readers' own scoping so writer and readers agree on
    what "inside the block" means.
    """
    heading = _ADDRESSES_HEADING_RE.search(text)
    if heading is None:
        return None
    start = heading.end()
    nxt = _NEXT_H2_RE.search(text[start:])
    return (start, start + nxt.start()) if nxt else (start, len(text))


def migrate(text: str) -> tuple[str, int | None]:
    """Return `(migrated_text, found_version)` for a profile's full contents.

    `found_version` is the version the block carried — None for the legacy
    pre-versioned block. `migrated_text` is byte-identical to `text` when the
    block is already current.

    Raises:
        ValueError: no `## Addresses` block, an unreadable `schema_version`
            value, a version ABOVE the current one, or a block missing a
            `REQUIRED_KEYS` entry. A future stamp means this writer is the
            lagging side; rewriting it would DOWNGRADE a block a newer owner
            wrote, so it refuses.

    Required keys are checked only on the paths that WRITE. A block already at
    the current version is returned untouched whatever it contains — this
    script's job is the stamp, and hard-failing every session over a shape
    problem it is not about to change would take bootstrap down with it. The
    readers surface that: `home_address.py` raises on a missing `current_home`.
    """
    bounds = _block_bounds(text)
    if bounds is None:
        raise ValueError("no `## Addresses` block")
    start, end = bounds
    block = text[start:end]

    match = _SCHEMA_LINE_RE.search(block)
    if match is None:
        # Legacy pre-versioned block: the field was introduced at v1, so a block
        # without it is v1. Insert the stamp as the block's first list line, the
        # position the canonical shape documents.
        found = None
        _require_keys(block)
        stamped = _insert_stamp(block)
    else:
        try:
            found = int(match["value"])
        except ValueError as exc:
            raise ValueError(f"unreadable schema_version {match['value']!r}") from exc
        if found > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"block is at schema_version={found}, above this writer's "
                f"{CURRENT_SCHEMA_VERSION}"
            )
        if found == CURRENT_SCHEMA_VERSION:
            return text, found
        _require_keys(block)
        stamped = (
            block[: match.start()]
            + f"{match['prefix']}{CURRENT_SCHEMA_VERSION}{match['trailing']}"
            + block[match.end() :]
        )

    stamped = _COMMENT_VERSION_RE.sub(
        lambda m: f"{m['prefix']}{CURRENT_SCHEMA_VERSION}", stamped, count=1
    )
    return text[:start] + stamped + text[end:], found


def _require_keys(block: str) -> None:
    """Raise unless every `REQUIRED_KEYS` entry is present with a non-empty value."""
    missing = [
        key
        for key in REQUIRED_KEYS
        # Horizontal whitespace only: `\s*` after the colon would cross the
        # newline and read the NEXT line's `-` as this key's value, so a blank
        # `- current_home:` would look populated.
        if not re.search(rf"^[ \t]*-[ \t]*{re.escape(key)}[ \t]*:[ \t]*\S", block, re.MULTILINE)
    ]
    if missing:
        raise ValueError("block is missing required key(s): " + ", ".join(missing))


def _insert_stamp(block: str) -> str:
    """A legacy block with `- schema_version: N` added above its first entry.

    Callers run `_require_keys` first, so the block has at least one entry to
    insert above.
    """
    lines = block.split("\n")
    for index, line in enumerate(lines):
        if line.lstrip().startswith("-"):
            lines.insert(index, f"- schema_version: {CURRENT_SCHEMA_VERSION}")
            return "\n".join(lines)
    raise ValueError("block is missing required key(s): " + ", ".join(REQUIRED_KEYS))


def profile_path(override: str | None = None) -> Path:
    """The profile path: `--profile`, else `$USER_PROFILE_PATH`, else the default."""
    if override:
        return Path(override)
    return Path(os.environ.get(PROFILE_PATH_ENV, DEFAULT_PROFILE_PATH))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate the owner profile's `## Addresses` block to the current schema."
    )
    parser.add_argument("--profile", help="owner-profile path (overrides USER_PROFILE_PATH)")
    args = parser.parse_args(argv)

    target = profile_path(args.profile)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(
            f"migrate-addresses-block: owner profile not found at {target} — the "
            "canonical `## Addresses` block lives in user_profile.md; create it "
            "(see skills/trusted-memory/state-schema.md) and re-run",
            file=sys.stderr,
        )
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"migrate-addresses-block: cannot read {target} ({type(exc).__name__}) — "
            "fix the file's permissions/encoding and re-run",
            file=sys.stderr,
        )
        return 1

    try:
        migrated_text, found = migrate(text)
    except ValueError as exc:
        print(
            f"migrate-addresses-block: {exc} in {target} — see "
            "skills/trusted-memory/state-schema.md for the canonical block shape; "
            "a stamp above this writer's version means upgrading this plugin, "
            "never hand-editing the block down",
            file=sys.stderr,
        )
        return 1

    changed = migrated_text != text
    if changed:
        try:
            write_atomic(target, migrated_text)
        except OSError as exc:
            print(
                f"migrate-addresses-block: cannot write {target} ({exc}) — the block "
                "is unchanged on disk; fix the permissions/mount and re-run",
                file=sys.stderr,
            )
            return 1

    print(
        json.dumps(
            {
                "migrated": changed,
                "from": found,
                "to": CURRENT_SCHEMA_VERSION,
                "path": str(target),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
