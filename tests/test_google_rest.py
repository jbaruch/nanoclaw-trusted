"""Tests for skills/google-ops/scripts/google-rest.py.

Locks down the native Google REST transport (nanoclaw#638) that replaced
`composio-rest.py`:

  - `google_request` issues the verb it is handed (GET/POST/PATCH/DELETE),
    url-encodes `params` (list values as repeated keys via `doseq`), and
    JSON-encodes `body` with a content-type
  - an empty/204 response is `{}`, not a JSONDecodeError every caller guards
  - 401 -> GatewayNotInjecting and 403+`access_restricted` ->
    TierAccessRestricted, the two config failure modes a bare status hides;
    a plain 403 and every other non-2xx stay an ordinary HTTPError for the
    caller to wrap
  - `surface_url` joins a known surface, KeyErrors an unknown one
  - `api_bases()` applies the GOOGLE_API_BASES override per call

The credential invariant is the point of #638 and is asserted on EVERY
request this suite makes (see `_assert_no_credentials`): the container holds
no Google credential, and the OneCLI gateway injects `Authorization` on the
wire. A request that carried its own auth header would mean a credential
leaked into the container — a security regression, not a fallback.

The local http.server fixture mirrors tests/test_google_calendar.py.
"""

import json
import threading
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/google-ops/scripts/google-rest.py"


def _load():
    return load_script("google_rest_under_test", SCRIPT_REL)


class _MockServer(HTTPServer):
    """HTTPServer carrying the per-test response fixtures the handler reads."""

    requests_seen: list[dict[str, Any]]
    response_body: Any
    response_status: int


class _Handler(BaseHTTPRequestHandler):
    def _record_and_reply(self) -> None:
        # This handler only ever runs under _MockServer (see google_api fixture).
        server = cast("_MockServer", self.server)
        split = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        server.requests_seen.append(
            {
                "method": self.command,
                # self.path is the raw request target — asserting on it proves
                # the encoding the transport applied, not our own.
                "path": split.path,
                "raw_query": split.query,
                "query": urllib.parse.parse_qs(split.query),
                "body": json.loads(raw) if raw else None,
                "raw_body": raw,
                "headers": {k.lower(): v for k, v in self.headers.items()},
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
def google_rest():
    return _load()


@pytest.fixture
def google_api(monkeypatch):
    """A local Gmail-surface stand-in, reached through GOOGLE_API_BASES.

    google-rest.py reads that env var per call, so the override lands
    without monkeypatching across an importlib boundary.
    """
    # Bind HTTPServer to port 0 directly and read the assigned port — no
    # close-then-rebind window another process could grab (TOCTOU race).
    httpd = _MockServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    httpd.requests_seen = []
    httpd.response_body = {"ok": True}
    httpd.response_status = 200
    # poll_interval bounds how long shutdown() blocks; the 0.5s default costs
    # half a second per test in teardown alone.
    threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True).start()
    monkeypatch.setenv(
        "GOOGLE_API_BASES",
        json.dumps({"gmail": f"http://127.0.0.1:{port}/gmail/v1"}),
    )
    # The transport deliberately honours the ambient proxy env (that is how
    # the OneCLI gateway gets on the request path in production). A proxy set
    # on the dev machine would otherwise silently reroute these fixture calls,
    # so the suite pins the request path at the loopback server.
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _assert_no_credentials(seen: dict) -> None:
    """The #638 invariant: this container holds no Google credential, so the
    transport must never put one on the wire. The gateway injects the Bearer
    in the TLS MITM; an Authorization header from here means a credential
    leaked into the container."""
    assert "authorization" not in seen["headers"]
    assert "x-api-key" not in seen["headers"]
    assert "x-goog-api-key" not in seen["headers"]


def _url(google_rest, path="users/me/messages"):
    return google_rest.surface_url("gmail", path)


# --- verbs --------------------------------------------------------------


def test_get_issues_a_bare_get_with_no_body(google_rest, google_api):
    google_api.response_body = {"messages": [{"id": "m1"}]}

    out = google_rest.google_request("GET", _url(google_rest))

    assert out == {"messages": [{"id": "m1"}]}
    seen = google_api.requests_seen[0]
    assert seen["method"] == "GET"
    assert seen["path"] == "/gmail/v1/users/me/messages"
    assert seen["body"] is None
    assert seen["headers"]["accept"] == "application/json"
    # No body means no content-type — nothing to describe.
    assert "content-type" not in seen["headers"]
    _assert_no_credentials(seen)


def test_post_json_encodes_the_body_and_sets_content_type(google_rest, google_api):
    google_api.response_body = {"id": "created"}

    out = google_rest.google_request(
        "POST", _url(google_rest, "users/me/labels"), body={"name": "Triage", "hidden": False}
    )

    assert out == {"id": "created"}
    seen = google_api.requests_seen[0]
    assert seen["method"] == "POST"
    assert seen["body"] == {"name": "Triage", "hidden": False}
    assert seen["headers"]["content-type"] == "application/json"
    # JSON false, not Python False — Google rejects the latter.
    assert '"hidden": false' in seen["raw_body"]
    _assert_no_credentials(seen)


def test_patch_sends_the_body_under_the_patch_verb(google_rest, google_api):
    google_rest.google_request(
        "PATCH", _url(google_rest, "users/me/settings"), body={"displayLanguage": "en"}
    )

    seen = google_api.requests_seen[0]
    assert seen["method"] == "PATCH"
    assert seen["body"] == {"displayLanguage": "en"}
    _assert_no_credentials(seen)


def test_delete_with_empty_204_body_returns_empty_dict(google_rest, google_api):
    """Calendar/Tasks DELETE answers 204 with no content. An empty body is
    success — callers must not each guard a JSONDecodeError for it."""
    google_api.response_status = 204

    out = google_rest.google_request("DELETE", _url(google_rest, "users/me/messages/m1"))

    assert out == {}
    seen = google_api.requests_seen[0]
    assert seen["method"] == "DELETE"
    _assert_no_credentials(seen)


# --- params -------------------------------------------------------------


def test_params_are_url_encoded_onto_the_query_string(google_rest, google_api):
    google_rest.google_request(
        "GET", _url(google_rest), params={"maxResults": 20, "q": "is:unread from:a@b.com"}
    )

    seen = google_api.requests_seen[0]
    assert seen["query"] == {"maxResults": ["20"], "q": ["is:unread from:a@b.com"]}
    assert seen["path"] == "/gmail/v1/users/me/messages"


def test_list_params_repeat_the_key_rather_than_encoding_a_python_repr(google_rest, google_api):
    """`doseq` is load-bearing: Gmail expects `labelIds=A&labelIds=B`. Without
    it urlencode sends the list's Python repr, which silently matches nothing."""
    google_rest.google_request("GET", _url(google_rest), params={"labelIds": ["INBOX", "UNREAD"]})

    seen = google_api.requests_seen[0]
    assert seen["query"]["labelIds"] == ["INBOX", "UNREAD"]
    assert "labelIds=INBOX&labelIds=UNREAD" in seen["raw_query"]
    assert "%5B" not in seen["raw_query"]  # no url-encoded "["


def test_params_append_with_ampersand_when_the_url_already_has_a_query(google_rest, google_api):
    google_rest.google_request("GET", _url(google_rest) + "?alt=json", params={"maxResults": 5})

    seen = google_api.requests_seen[0]
    assert seen["query"] == {"alt": ["json"], "maxResults": ["5"]}


def test_empty_params_add_no_query_string(google_rest, google_api):
    google_rest.google_request("GET", _url(google_rest), params={})

    assert google_api.requests_seen[0]["raw_query"] == ""


# --- error classification -----------------------------------------------


def test_401_raises_gateway_not_injecting(google_rest, google_api):
    google_api.response_status = 401
    google_api.response_body = {"error": {"message": "Invalid Credentials"}}

    with pytest.raises(google_rest.GatewayNotInjecting) as exc:
        google_rest.google_request("GET", _url(google_rest))

    # Actionable: names the two things an operator must check.
    assert "HTTPS_PROXY" in str(exc.value)
    assert "onecli apps list" in str(exc.value)
    # The upstream detail rides along so the operator sees what Google said.
    assert "Invalid Credentials" in str(exc.value)


def test_403_with_access_restricted_raises_tier_access_restricted(google_rest, google_api):
    google_api.response_status = 403
    google_api.response_body = {"error": {"status": "access_restricted"}}

    with pytest.raises(google_rest.TierAccessRestricted) as exc:
        google_rest.google_request("GET", _url(google_rest))

    assert "secretMode" in str(exc.value)
    assert "untrusted tier" in str(exc.value)


def test_plain_403_stays_an_ordinary_http_error(google_rest, google_api):
    """Only the `access_restricted` marker means the tier gate. A 403 for
    insufficient scope is a real fault the caller wraps into its own marker."""
    google_api.response_status = 403
    google_api.response_body = {"error": {"message": "insufficient scope"}}

    with pytest.raises(urllib.error.HTTPError) as exc:
        google_rest.google_request("GET", _url(google_rest))

    assert exc.value.code == 403
    assert not isinstance(exc.value, google_rest.TierAccessRestricted)


def test_plain_403_keeps_googles_reason_after_the_marker_check(google_rest, google_api):
    """Sniffing for `access_restricted` reads the body, and reading drains
    it. An ordinary 403 must not be handed back with its detail consumed —
    the caller wraps `str(e)` into its own error marker, and a bare
    "HTTP Error 403: Forbidden" hides why Google actually refused."""
    google_api.response_status = 403
    google_api.response_body = {"error": {"message": "rateLimitExceeded"}}

    with pytest.raises(urllib.error.HTTPError) as exc:
        google_rest.google_request("GET", _url(google_rest))

    # The reason the caller stringifies carries the diagnostic...
    assert "rateLimitExceeded" in str(exc.value)
    # ...and the body is readable rather than drained to b"".
    assert b"rateLimitExceeded" in exc.value.read()


@pytest.mark.parametrize("status", [400, 404, 429, 500, 503])
def test_other_non_2xx_propagate_as_http_error(google_rest, google_api, status):
    google_api.response_status = status
    google_api.response_body = {"error": {"message": "nope"}}

    with pytest.raises(urllib.error.HTTPError) as exc:
        google_rest.google_request("GET", _url(google_rest))

    assert exc.value.code == status


def test_gateway_and_tier_errors_are_distinct_types(google_rest):
    """Callers branch on these separately: GatewayNotInjecting is a fault to
    alarm about, TierAccessRestricted is correct behaviour to report."""
    assert not issubclass(google_rest.GatewayNotInjecting, google_rest.TierAccessRestricted)
    assert not issubclass(google_rest.TierAccessRestricted, google_rest.GatewayNotInjecting)
    assert issubclass(google_rest.GatewayNotInjecting, RuntimeError)
    assert issubclass(google_rest.TierAccessRestricted, RuntimeError)


# --- surface_url / api_bases --------------------------------------------


def test_surface_url_joins_the_base_with_the_path(google_rest, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_BASES", raising=False)

    assert google_rest.surface_url("gmail", "users/me/messages") == (
        "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    )
    # A leading slash on the path must not double up the separator.
    assert google_rest.surface_url("tasks", "/users/@me/lists") == (
        "https://tasks.googleapis.com/tasks/v1/users/@me/lists"
    )


def test_surface_url_rejects_an_unknown_surface(google_rest):
    """KeyError rather than a silently-built URL the gateway has no app
    binding for — that would 401 as if the gateway were broken."""
    with pytest.raises(KeyError) as exc:
        google_rest.surface_url("sheets", "spreadsheets")

    assert "sheets" in str(exc.value)


def test_api_bases_defaults_cover_the_four_brokered_surfaces(google_rest, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_BASES", raising=False)

    assert set(google_rest.api_bases()) == {"gmail", "calendar", "tasks", "drive"}


def test_api_bases_applies_the_env_override_per_surface(google_rest, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_BASES", json.dumps({"gmail": "http://localhost:9/gmail/v1"}))

    bases = google_rest.api_bases()

    assert bases["gmail"] == "http://localhost:9/gmail/v1"
    # Overriding one surface leaves the others at their defaults.
    assert bases["calendar"] == google_rest.DEFAULT_API_BASES["calendar"]


def test_api_bases_is_read_per_call_not_captured_at_import(google_rest, monkeypatch):
    """The override must cross the importlib boundary a caller loads this
    module through — so it is read on every call, never cached at import."""
    monkeypatch.delenv("GOOGLE_API_BASES", raising=False)
    assert google_rest.api_bases()["gmail"] == google_rest.DEFAULT_API_BASES["gmail"]

    monkeypatch.setenv("GOOGLE_API_BASES", json.dumps({"gmail": "http://localhost:9/g"}))
    assert google_rest.api_bases()["gmail"] == "http://localhost:9/g"


def test_api_bases_does_not_mutate_the_default_table(google_rest, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_BASES", json.dumps({"gmail": "http://localhost:9/g"}))

    google_rest.api_bases()

    assert google_rest.DEFAULT_API_BASES["gmail"] == "https://gmail.googleapis.com/gmail/v1"
