"""Tests for skills/google-ops/scripts/google-tasks.py.

Locks down the native Tasks REST op contract (nanoclaw#638):

  - each op maps to its fixed method + endpoint (list-tasklists / list /
    get / patch / insert / delete)
  - tasklist_id / task_id are lifted out of stdin onto the URL path,
    URL-quoted, and never re-appear in the body or query
  - patch/insert send their remaining stdin keys as a JSON body;
    everything else sends them as query params
  - delete's 204-with-no-body surfaces as {}
  - the raw Tasks resource is printed — no Composio envelope, and no
    `successful: false` in-band failure branch (Google uses HTTP status)
  - per-op required keys are enforced locally with an actionable error
    (exit 2) before any network call
  - HTTP failures exit non-zero with no stdout; 401 is the
    gateway-not-injecting path, 403 + access_restricted the tier-gated one

Same fixture-server strategy as test_google_calendar.py: google-rest reads
GOOGLE_API_BASES from the env per call, so the local server URL reaches
the internally-loaded module.
"""

import importlib.util
import io
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills/google-ops/scripts/google-tasks.py"

TASKLIST = "MDg5Mzc2MTgxNzUxMzkxMjEzNDg6MDow"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("google_tasks_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _MockServer(HTTPServer):
    """HTTPServer carrying the per-test response fixtures the handler reads."""

    requests_seen: list[dict[str, Any]]
    response_body: Any
    response_status: int


class _Handler(BaseHTTPRequestHandler):
    def _record_and_reply(self) -> None:
        # This handler only ever runs under _MockServer (see tasks_api fixture).
        server = cast("_MockServer", self.server)
        split = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        server.requests_seen.append(
            {
                "method": self.command,
                # self.path is the raw request target — asserting on it
                # proves the quoting the script applied, not our own.
                "path": split.path,
                "query": urllib.parse.parse_qs(split.query),
                "body": json.loads(raw) if raw else None,
            }
        )
        if server.response_status == 204:
            self.send_response(204)
            self.end_headers()
            return
        payload = json.dumps(server.response_body).encode("utf-8")
        self.send_response(server.response_status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler API
        self._record_and_reply()

    def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler API
        self._record_and_reply()

    def do_PATCH(self):  # noqa: N802 — BaseHTTPRequestHandler API
        self._record_and_reply()

    def do_DELETE(self):  # noqa: N802 — BaseHTTPRequestHandler API
        self._record_and_reply()

    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture
def tasks_api(monkeypatch):
    # Bind HTTPServer to port 0 directly and read the assigned port — no
    # close-then-rebind window another process could grab (TOCTOU race).
    httpd = _MockServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    httpd.requests_seen = []
    httpd.response_body = {"items": []}
    httpd.response_status = 200
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv(
        "GOOGLE_API_BASES",
        json.dumps({"tasks": f"http://127.0.0.1:{port}/tasks/v1"}),
    )
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _run(monkeypatch, op, stdin_obj):
    module = _load()
    monkeypatch.setattr("sys.argv", ["google-tasks.py", op])
    text = stdin_obj if isinstance(stdin_obj, str) else json.dumps(stdin_obj)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    return module.main()


def test_list_tasklists_gets_the_users_lists_collection(tasks_api, monkeypatch, capsys):
    tasks_api.response_body = {"items": [{"id": "L1"}]}

    rc = _run(monkeypatch, "list-tasklists", {})

    assert rc == 0
    seen = tasks_api.requests_seen[0]
    assert seen["method"] == "GET"
    assert seen["path"] == "/tasks/v1/users/@me/lists"
    assert seen["query"] == {}
    assert seen["body"] is None
    # Raw resource, no envelope: the array is top-level `items`.
    assert json.loads(capsys.readouterr().out.strip()) == {"items": [{"id": "L1"}]}


def test_list_gets_the_tasks_collection_with_the_id_on_the_path(tasks_api, monkeypatch, capsys):
    tasks_api.response_body = {"items": [{"id": "t1"}]}

    rc = _run(monkeypatch, "list", {"tasklist_id": TASKLIST})

    assert rc == 0
    seen = tasks_api.requests_seen[0]
    assert seen["method"] == "GET"
    assert seen["path"] == f"/tasks/v1/lists/{TASKLIST}/tasks"
    # tasklist_id is a path segment natively — it must not also be a query param.
    assert seen["query"] == {}
    assert seen["body"] is None


def test_list_sends_remaining_stdin_keys_as_query_params(tasks_api, monkeypatch, capsys):
    rc = _run(
        monkeypatch,
        "list",
        {"tasklist_id": TASKLIST, "showCompleted": "true", "maxResults": "50"},
    )

    assert rc == 0
    seen = tasks_api.requests_seen[0]
    assert seen["path"] == f"/tasks/v1/lists/{TASKLIST}/tasks"
    assert seen["query"] == {"showCompleted": ["true"], "maxResults": ["50"]}
    assert "tasklist_id" not in seen["query"]
    assert seen["body"] is None


def test_list_serializes_json_booleans_as_true_false(tasks_api, monkeypatch, capsys):
    # A caller writing stdin JSON sends a real boolean, not the string
    # "true". Python's urlencode would stringify it as `True`, which Tasks
    # rejects as a malformed value — so the transport must lower-case it.
    rc = _run(
        monkeypatch,
        "list",
        {"tasklist_id": TASKLIST, "showCompleted": True, "showHidden": False},
    )

    assert rc == 0
    seen = tasks_api.requests_seen[0]
    assert seen["query"] == {"showCompleted": ["true"], "showHidden": ["false"]}


def test_get_puts_both_ids_on_the_path(tasks_api, monkeypatch, capsys):
    tasks_api.response_body = {"id": "t1", "title": "Renew passport"}

    rc = _run(monkeypatch, "get", {"tasklist_id": TASKLIST, "task_id": "t1"})

    assert rc == 0
    seen = tasks_api.requests_seen[0]
    assert seen["method"] == "GET"
    assert seen["path"] == f"/tasks/v1/lists/{TASKLIST}/tasks/t1"
    assert seen["query"] == {}
    assert json.loads(capsys.readouterr().out.strip()) == {"id": "t1", "title": "Renew passport"}


def test_ids_are_url_quoted_into_the_path(tasks_api, monkeypatch, capsys):
    rc = _run(monkeypatch, "get", {"tasklist_id": "list/one:0", "task_id": "task id+1"})

    assert rc == 0
    assert (
        tasks_api.requests_seen[0]["path"] == "/tasks/v1/lists/list%2Fone%3A0/tasks/task%20id%2B1"
    )


def test_patch_sends_a_json_body_with_the_ids_stripped(tasks_api, monkeypatch, capsys):
    tasks_api.response_body = {"id": "t1", "status": "completed"}

    rc = _run(
        monkeypatch,
        "patch",
        {
            "tasklist_id": TASKLIST,
            "task_id": "t1",
            "title": "Renew passport",
            "status": "completed",
            "due": "2026-06-15T00:00:00.000Z",
        },
    )

    assert rc == 0
    seen = tasks_api.requests_seen[0]
    assert seen["method"] == "PATCH"
    assert seen["path"] == f"/tasks/v1/lists/{TASKLIST}/tasks/t1"
    assert seen["query"] == {}
    assert seen["body"] == {
        "title": "Renew passport",
        "status": "completed",
        "due": "2026-06-15T00:00:00.000Z",
    }


def test_insert_posts_a_json_body_to_the_tasks_collection(tasks_api, monkeypatch, capsys):
    tasks_api.response_body = {"id": "t9"}

    rc = _run(
        monkeypatch,
        "insert",
        {
            "tasklist_id": TASKLIST,
            "title": "08:00 UTC-05:00 — call dealer",
            "status": "needsAction",
            "due": "2026-06-15T00:00:00.000Z",
        },
    )

    assert rc == 0
    seen = tasks_api.requests_seen[0]
    assert seen["method"] == "POST"
    assert seen["path"] == f"/tasks/v1/lists/{TASKLIST}/tasks"
    assert seen["query"] == {}
    assert seen["body"] == {
        "title": "08:00 UTC-05:00 — call dealer",
        "status": "needsAction",
        "due": "2026-06-15T00:00:00.000Z",
    }


def test_delete_204_with_no_body_returns_an_empty_object(tasks_api, monkeypatch, capsys):
    tasks_api.response_status = 204

    rc = _run(monkeypatch, "delete", {"tasklist_id": TASKLIST, "task_id": "t1"})

    assert rc == 0
    seen = tasks_api.requests_seen[0]
    assert seen["method"] == "DELETE"
    assert seen["path"] == f"/tasks/v1/lists/{TASKLIST}/tasks/t1"
    # An empty body is success, not a JSONDecodeError for callers to guard.
    assert json.loads(capsys.readouterr().out.strip()) == {}


def test_patch_missing_required_status_exits_2_before_network(tasks_api, monkeypatch, capsys):
    rc = _run(
        monkeypatch,
        "patch",
        {"tasklist_id": TASKLIST, "task_id": "t1", "title": "x"},  # no status
    )

    assert rc == 2
    assert "missing/empty: status" in capsys.readouterr().err
    assert tasks_api.requests_seen == []


def test_list_missing_tasklist_id_exits_2(tasks_api, monkeypatch, capsys):
    rc = _run(monkeypatch, "list", {})
    assert rc == 2
    assert "missing/empty: tasklist_id" in capsys.readouterr().err
    assert tasks_api.requests_seen == []


def test_insert_missing_title_and_status_exits_2(tasks_api, monkeypatch, capsys):
    rc = _run(monkeypatch, "insert", {"tasklist_id": TASKLIST})
    assert rc == 2
    err = capsys.readouterr().err
    assert "missing/empty: title, status" in err
    assert tasks_api.requests_seen == []


def test_http_500_exits_nonzero_with_no_stdout(tasks_api, monkeypatch, capsys):
    tasks_api.response_status = 500
    tasks_api.response_body = {"error": {"message": "backend error"}}

    rc = _run(monkeypatch, "list", {"tasklist_id": TASKLIST})

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "list call failed" in captured.err


def test_401_reports_the_gateway_not_injecting(tasks_api, monkeypatch, capsys):
    tasks_api.response_status = 401
    tasks_api.response_body = {"error": {"message": "Invalid Credentials"}}

    rc = _run(monkeypatch, "list", {"tasklist_id": TASKLIST})

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "unauthenticated" in captured.err
    assert "HTTPS_PROXY" in captured.err


def test_403_access_restricted_reports_the_tier_gate(tasks_api, monkeypatch, capsys):
    tasks_api.response_status = 403
    tasks_api.response_body = {"error": {"status": "access_restricted"}}

    rc = _run(monkeypatch, "get", {"tasklist_id": TASKLIST, "task_id": "t1"})

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "unavailable at this tier" in captured.err


def test_unknown_op_exits_2(monkeypatch, capsys):
    module = _load()
    monkeypatch.setattr("sys.argv", ["google-tasks.py", "move"])  # not a defined op
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    rc = module.main()
    assert rc == 2
    assert "usage" in capsys.readouterr().err


def test_invalid_stdin_json_exits_2(tasks_api, monkeypatch, capsys):
    rc = _run(monkeypatch, "list", "{not json")
    assert rc == 2
    assert "invalid stdin" in capsys.readouterr().err
    assert tasks_api.requests_seen == []


def test_non_object_stdin_exits_2(tasks_api, monkeypatch, capsys):
    rc = _run(monkeypatch, "list", '"a string"')
    assert rc == 2
    assert "invalid stdin" in capsys.readouterr().err
    assert tasks_api.requests_seen == []
