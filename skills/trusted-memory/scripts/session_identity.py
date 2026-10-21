"""Resolve the bootstrap identity shared by both sentinel readers and writers."""

import os
from collections.abc import Mapping


def current_session_id(environ: Mapping[str, str] | None = None) -> str:
    """Keep explicit legacy identity precedence, then use Claude Code's identity."""
    values = os.environ if environ is None else environ
    return values.get("CLAUDE_SESSION_ID") or values.get("CLAUDE_CODE_SESSION_ID") or ""
