"""Tests for skills/google-ops/scripts/google-calendar.py.

Locks down the native Calendar REST contract (nanoclaw#638):

  - op `events-list` GETs /calendars/{calendarId}/events on the calendar
    surface, with calendarId as a URL-quoted path segment
  - calendarId defaults to "primary"; singleEvents defaults to "true";
    stdin overrides merge over both
  - JSON booleans reach the wire as true/false, never True/False
  - the raw Calendar resource is printed — no Composio envelope, and no
    `successful: false` in-band failure branch (Google uses HTTP status)
  - HTTP failures exit non-zero with no stdout; 401 is the
    gateway-not-injecting path, 403 + access_restricted the tier-gated one
  - bad input / unknown op exit 2

google-rest.py reads GOOGLE_API_BASES from the env per call, so pointing
that env var at a local fixture server reaches the internally-loaded
module without monkeypatching across the importlib boundary.
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
SCRIPT_PATH = REPO_ROOT / "skills/google-ops/scripts/google-calendar.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("google_calendar_under_test", SCRIPT_PATH)
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
        # This handler only ever runs under _MockServer (see mock_server fixture).
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

    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture
def calendar_api(monkeypatch):
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
        json.dumps({"calendar": f"http://127.0.0.1:{port}/calendar/v3"}),
    )
    # The transport deliberately honours the ambient proxy env (that is how
    # the OneCLI gateway gets on the request path in production). A proxy set
    # on the dev machine or CI runner would otherwise silently reroute these
    # fixture calls, so pin the request path at the loopback server.
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _run(monkeypatch, stdin_obj):
    module = _load()
    monkeypatch.setattr("sys.argv", ["google-calendar.py", "events-list"])
    text = stdin_obj if isinstance(stdin_obj, str) else json.dumps(stdin_obj)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    return module.main()


def test_events_list_defaults_to_primary_calendar_and_single_events(
    calendar_api, monkeypatch, capsys
):
    calendar_api.response_body = {"items": [{"id": "e1"}]}

    rc = _run(monkeypatch, "")

    assert rc == 0
    seen = calendar_api.requests_seen[0]
    assert seen["method"] == "GET"
    assert seen["path"] == "/calendar/v3/calendars/primary/events"
    assert seen["query"] == {"singleEvents": ["true"]}
    assert seen["body"] is None


def test_raw_calendar_resource_is_printed_without_an_envelope(calendar_api, monkeypatch, capsys):
    calendar_api.response_body = {"kind": "calendar#events", "items": [{"id": "e1"}]}

    rc = _run(monkeypatch, "")

    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip())
    # Events are top-level `items`, not `data.items`; no successful/error keys.
    assert out == {"kind": "calendar#events", "items": [{"id": "e1"}]}


def test_email_calendar_id_is_url_quoted_into_the_path(calendar_api, monkeypatch, capsys):
    rc = _run(monkeypatch, {"calendarId": "work+team@example.com"})

    assert rc == 0
    seen = calendar_api.requests_seen[0]
    assert seen["path"] == "/calendar/v3/calendars/work%2Bteam%40example.com/events"
    # calendarId is a path segment natively — it must not also be a query param.
    assert "calendarId" not in seen["query"]


def test_stdin_overrides_merge_over_defaults(calendar_api, monkeypatch, capsys):
    rc = _run(
        monkeypatch,
        {
            "timeMin": "2026-06-01T00:00:00Z",
            "timeMax": "2026-06-02T00:00:00Z",
            "orderBy": "startTime",
        },
    )

    assert rc == 0
    seen = calendar_api.requests_seen[0]
    assert seen["path"] == "/calendar/v3/calendars/primary/events"
    assert seen["query"] == {
        "singleEvents": ["true"],  # default preserved
        "timeMin": ["2026-06-01T00:00:00Z"],
        "timeMax": ["2026-06-02T00:00:00Z"],
        "orderBy": ["startTime"],
    }


def test_json_booleans_serialize_as_true_false_not_python_repr(calendar_api, monkeypatch, capsys):
    rc = _run(monkeypatch, {"singleEvents": False, "showDeleted": True})

    assert rc == 0
    query = calendar_api.requests_seen[0]["query"]
    # Python's str() would send True/False, which Calendar rejects.
    assert query["singleEvents"] == ["false"]
    assert query["showDeleted"] == ["true"]


def test_empty_calendar_id_falls_back_to_the_primary_default(calendar_api, monkeypatch, capsys):
    rc = _run(monkeypatch, {"calendarId": "", "orderBy": "startTime"})

    assert rc == 0
    assert calendar_api.requests_seen[0]["path"] == "/calendar/v3/calendars/primary/events"


def test_http_500_exits_nonzero_with_no_stdout(calendar_api, monkeypatch, capsys):
    calendar_api.response_status = 500
    calendar_api.response_body = {"error": {"message": "backend error"}}

    rc = _run(monkeypatch, "")

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "events-list call failed" in captured.err


def test_401_reports_the_gateway_not_injecting(calendar_api, monkeypatch, capsys):
    calendar_api.response_status = 401
    calendar_api.response_body = {"error": {"message": "Invalid Credentials"}}

    rc = _run(monkeypatch, "")

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "unauthenticated" in captured.err
    assert "HTTPS_PROXY" in captured.err


def test_403_access_restricted_reports_the_tier_gate(calendar_api, monkeypatch, capsys):
    calendar_api.response_status = 403
    calendar_api.response_body = {"error": {"status": "access_restricted"}}

    rc = _run(monkeypatch, "")

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "unavailable at this tier" in captured.err


def test_plain_403_without_the_marker_is_an_ordinary_failure(calendar_api, monkeypatch, capsys):
    calendar_api.response_status = 403
    calendar_api.response_body = {"error": {"message": "insufficient scope"}}

    rc = _run(monkeypatch, "")

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "events-list call failed" in captured.err


def test_unknown_op_exits_2(monkeypatch, capsys):
    module = _load()
    monkeypatch.setattr("sys.argv", ["google-calendar.py", "bogus-op"])
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    rc = module.main()
    assert rc == 2
    assert "usage" in capsys.readouterr().err


def test_invalid_stdin_json_exits_2(calendar_api, monkeypatch, capsys):
    rc = _run(monkeypatch, "{not json")
    assert rc == 2
    assert "invalid stdin" in capsys.readouterr().err
    assert calendar_api.requests_seen == []


def test_non_object_stdin_exits_2(calendar_api, monkeypatch, capsys):
    rc = _run(monkeypatch, "[1, 2]")
    assert rc == 2
    assert "invalid stdin" in capsys.readouterr().err
    assert calendar_api.requests_seen == []
