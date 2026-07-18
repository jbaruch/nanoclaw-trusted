#!/usr/bin/env python3
"""Headless Google Tasks ops over the native Tasks REST API (nanoclaw#638).

Replaces `composio-tasks.py`. The ops and their stdin contract are
unchanged; what changed is the wire and the output shape:

    list-tasklists -> GET    /users/@me/lists
    list           -> GET    /lists/{tasklist_id}/tasks
    get            -> GET    /lists/{tasklist_id}/tasks/{task_id}
    patch          -> PATCH  /lists/{tasklist_id}/tasks/{task_id}
    insert         -> POST   /lists/{tasklist_id}/tasks
    delete         -> DELETE /lists/{tasklist_id}/tasks/{task_id}

`tasklist_id` / `task_id` keep their snake_case stdin names. They were
snake_case because the Composio slug demanded it; they stay snake_case
because that is this script's own contract and every caller already
speaks it. Natively they are path segments, not body fields — this script
lifts them out of stdin and onto the URL. Every remaining key is the
native Tasks field name (`title`, `status`, `due`, `notes`), so callers'
stdin JSON carries over unchanged.

Output shape changed — read the resource, not `data`
----------------------------------------------------
Composio wrapped every response in `{"data": ..., "successful": bool,
"error": ...}`. That envelope was a Composio invention and dies with it:
this script prints the raw Tasks resource. `list-tasklists` and `list`
put their array in top-level `items`; `get` / `patch` / `insert` return
the task resource itself. `delete` answers 204 with no body, which
surfaces as `{}`.

The `successful: false` branch dies too. Composio reported an API-level
failure (task not found, insufficient scope) as HTTP 200 with
`successful: false` in the body, so callers had to test a field to notice.
Google reports those as real HTTP status codes, so they arrive here as an
HTTPError and exit non-zero. A zero exit now means the call succeeded.

Credential model: none in this container. OneCLI's gateway injects the
Bearer on the wire and refreshes it (see `google-rest.py`). The
`COMPOSIO_API_KEY` / `COMPOSIO_USER_ID` preflight is gone with the
credential — the gateway's absence surfaces as `GatewayNotInjecting`
(401) rather than as a missing env var.

Black box per `coding-policy: script-as-black-box`: the consuming skill
names the arguments contract; this script maps the op to its endpoint and
validates per-op required keys before the call. The agent supplies the
computed arguments (task ids, due dates, titles) as a JSON object on
stdin — that computation is reasoning, not a fixed transform.

Usage
-----
    echo '{}' | google-tasks.py list-tasklists
    echo '{"tasklist_id": "..."}' | google-tasks.py list
    echo '{"tasklist_id": "...", "task_id": "..."}' | google-tasks.py get
    echo '{"tasklist_id": "...", "task_id": "...", "title": "...", \
           "status": "needsAction", "due": "...Z"}' | google-tasks.py patch
    echo '{"tasklist_id": "...", "title": "...", "status": "needsAction", \
           "due": "...Z"}' | google-tasks.py insert

Output
------
On success: the raw Tasks resource as single-line JSON on stdout, exit 0.

On failure (HTTP 4xx/5xx, gateway not injecting, tier-restricted,
network, timeout, bad JSON), malformed stdin, unknown op, or stdin
missing an op's required keys: a diagnostic on stderr and a non-zero
exit, no stdout.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import urllib.error
import urllib.parse

_SCRIPTS = pathlib.Path(__file__).resolve().parent
GOOGLE_REST_PATH = _SCRIPTS / "google-rest.py"

# Op -> (HTTP method, required stdin keys). Required keys are unchanged
# from the Composio path so a malformed call still fails here with an
# actionable message rather than as an opaque Google 4xx. `patch` keeps
# requiring title+status even though a native PATCH is partial: relaxing a
# caller contract is a change #638 does not need to make.
OPS = {
    "list-tasklists": ("GET", ()),
    "list": ("GET", ("tasklist_id",)),
    "get": ("GET", ("tasklist_id", "task_id")),
    "patch": ("PATCH", ("tasklist_id", "task_id", "title", "status")),
    "insert": ("POST", ("tasklist_id", "title", "status")),
    "delete": ("DELETE", ("tasklist_id", "task_id")),
}

# Ops whose non-path stdin keys form a request body rather than a query
# string. Everything else sends its leftovers as query params.
_BODY_OPS = {"patch", "insert"}


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
        raise ValueError("stdin must be a JSON object of Tasks arguments")
    return args


def _quote(value):
    """Quote a stdin-supplied id for use as a URL path segment. Task list
    ids are opaque Google strings that can carry URL-significant
    characters; `safe=''` keeps them from being read as path structure."""
    return urllib.parse.quote(str(value), safe="")


def _endpoint(op, args):
    """Build the op's path, consuming the id keys from `args` so what
    remains is the body/query payload."""
    if op == "list-tasklists":
        return "users/@me/lists"
    tasklist = _quote(args.pop("tasklist_id"))
    if op in ("list", "insert"):
        return f"lists/{tasklist}/tasks"
    return f"lists/{tasklist}/tasks/{_quote(args.pop('task_id'))}"


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in OPS:
        sys.stderr.write(f"google-tasks: usage: google-tasks.py <{'|'.join(OPS)}> (args on stdin)\n")
        return 2
    op = sys.argv[1]
    method, required = OPS[op]

    try:
        args = _read_stdin_args()
    except (json.JSONDecodeError, ValueError) as e:
        sys.stderr.write(f"google-tasks: invalid stdin ({e}).\n")
        return 2

    missing = [k for k in required if not args.get(k)]
    if missing:
        sys.stderr.write(
            f"google-tasks: {op} requires {', '.join(required)}; "
            f"missing/empty: {', '.join(missing)}.\n"
        )
        return 2

    try:
        google_rest = _load_google_rest()
    except (FileNotFoundError, PermissionError, ImportError, OSError) as e:
        sys.stderr.write(
            f"google-tasks: Google REST helper unavailable ({e}) — expected at {GOOGLE_REST_PATH}.\n"
        )
        return 2

    path = _endpoint(op, args)
    payload = {"body": args} if op in _BODY_OPS else {"params": args or None}

    try:
        resource = google_rest.google_request(
            method, google_rest.surface_url("tasks", path), **payload
        )
    except google_rest.GatewayNotInjecting as e:
        sys.stderr.write(f"google-tasks: {op} unauthenticated — {e}\n")
        return 1
    except google_rest.TierAccessRestricted as e:
        sys.stderr.write(f"google-tasks: {op} unavailable at this tier — {e}\n")
        return 1
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"google-tasks: {op} call failed ({type(e).__name__}: {e}).\n")
        return 1

    print(json.dumps(resource))
    return 0


if __name__ == "__main__":
    sys.exit(main())
