#!/usr/bin/env python3
"""Headless Google Calendar read over the native Calendar REST API (nanoclaw#638).

Replaces `composio-calendar.py`. The op and its stdin contract are
unchanged; what changed is the wire and the output shape:

    composio-calendar.py events-list  ->  google-calendar.py events-list
    POST /tools/execute/GOOGLECALENDAR_EVENTS_LIST
        -> GET /calendars/{calendarId}/events

Output shape changed — read `items`, not `data.items`
-----------------------------------------------------
Composio wrapped every response in its own envelope
(`{"data": ..., "successful": bool, "error": ...}`). That envelope was a
Composio invention, so it dies with Composio: this script prints the raw
Calendar resource, in which the event array is top-level `items`.

The `successful: false` branch dies with it too. Composio reported an
API-level failure (calendar not found, insufficient scope) as HTTP 200
with `successful: false` in the body, so callers had to test a field to
notice. Google reports the same failures as real HTTP status codes, so
they arrive here as an HTTPError and exit non-zero. A zero exit now means
the call succeeded; there is no in-band failure field left to check.

Credential model: none in this container. OneCLI's gateway injects the
Bearer on the wire and refreshes it (see `google-rest.py`). The
`COMPOSIO_API_KEY` / `COMPOSIO_USER_ID` preflight is gone with the
credential — the gateway's absence surfaces as `GatewayNotInjecting`
(401) rather than as a missing env var.

Black box per `coding-policy: script-as-black-box`: the consuming skill
names the arguments contract; this script owns the endpoint, the
`calendarId`/`singleEvents` defaults, and the query-param encoding.
Argument computation (time windows, timezone math) stays in the skill —
it is reasoning, not a fixed transform.

Usage
-----
    echo '{"timeMin": "...Z", "timeMax": "...Z", "orderBy": "startTime"}' \
        | google-calendar.py events-list

Reads a JSON object of Calendar arguments from stdin (empty stdin = no
overrides). Keys are the native Calendar query params — the same
camelCase names the Composio slug took, so callers' stdin JSON carries
over unchanged. `calendarId` selects the calendar (path param, defaults
to "primary"); every other key is passed through as a query param.
`singleEvents` defaults to true.

Output
------
On success: the raw Calendar resource as single-line JSON on stdout,
exit 0. Events are in `items`.

On failure (HTTP 4xx/5xx, gateway not injecting, tier-restricted,
network, timeout, bad JSON) or malformed stdin / unknown op: a
diagnostic on stderr and a non-zero exit, no stdout — so the consuming
skill surfaces the error and stops rather than acting on absent data.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import urllib.error
import urllib.parse

_SCRIPTS = pathlib.Path(__file__).resolve().parent
# google-rest.py is this script's sibling (the shared Google REST
# primitives live in this skill's scripts/ dir). Loaded by file path because the
# hyphenated filename is not a valid import name.
GOOGLE_REST_PATH = _SCRIPTS / "google-rest.py"

DEFAULT_CALENDAR_ID = "primary"
# singleEvents=true expands recurring events into individual instances.
# Every caller reads a concrete day's agenda, so the expanded form is what
# they mean; the unexpanded form would hand them a recurrence rule to
# interpret. orderBy=startTime is only legal alongside it.
DEFAULT_QUERY = {"singleEvents": "true"}


def _load_google_rest():
    spec = importlib.util.spec_from_file_location("google_rest", GOOGLE_REST_PATH)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"cannot load google-rest from {GOOGLE_REST_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_stdin_args() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    args = json.loads(raw)
    if not isinstance(args, dict):
        raise ValueError("stdin must be a JSON object of Calendar arguments")
    return args


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "events-list":
        sys.stderr.write("google-calendar: usage: google-calendar.py events-list (args on stdin)\n")
        return 2

    try:
        overrides = _read_stdin_args()
    except (json.JSONDecodeError, ValueError) as e:
        sys.stderr.write(f"google-calendar: invalid stdin ({e}).\n")
        return 2

    try:
        google_rest = _load_google_rest()
    except (FileNotFoundError, PermissionError, ImportError, OSError) as e:
        sys.stderr.write(
            f"google-calendar: Google REST helper unavailable ({e}) — "
            f"expected at {GOOGLE_REST_PATH}.\n"
        )
        return 2

    # Drop empty/None overrides so a blank `calendarId` can't shadow the
    # "primary" default and produce an opaque Calendar 4xx.
    args = {k: v for k, v in overrides.items() if v not in (None, "")}
    calendar_id = args.pop("calendarId", DEFAULT_CALENDAR_ID)
    # Booleans arriving from stdin JSON (`singleEvents`) are serialized by
    # google_request, not here — one encoder, so every op script agrees.
    params = {**DEFAULT_QUERY, **args}

    # calendarId is a path segment natively (it was a body field under
    # Composio) and is routinely an email address — quote it so the `@`
    # and any `+` reach Calendar intact.
    path = f"calendars/{urllib.parse.quote(str(calendar_id), safe='')}/events"

    try:
        resource = google_rest.google_request(
            "GET", google_rest.surface_url("calendar", path), params=params
        )
    except google_rest.GatewayNotInjecting as e:
        sys.stderr.write(f"google-calendar: events-list unauthenticated — {e}\n")
        return 1
    except google_rest.TierAccessRestricted as e:
        sys.stderr.write(f"google-calendar: events-list unavailable at this tier — {e}\n")
        return 1
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"google-calendar: events-list call failed ({type(e).__name__}: {e}).\n")
        return 1

    print(json.dumps(resource))
    return 0


if __name__ == "__main__":
    sys.exit(main())
