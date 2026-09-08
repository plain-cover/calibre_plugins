"""Connection ownership, budgets and grouped browser recovery regressions."""

import http.client
import io
import threading
from email.message import Message
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import List
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from common import common_romanceio_transport as transport
from common import common_romanceio_fetch_helper as helper
from common import common_romanceio_webengine as engine
from common import common_romanceio_json_api as api
from common import common_romanceio_search_orchestrator as orchestrator

URL = "https://www.romance.io/json/search_books?search=Title"


class Response(io.BytesIO):
    status = 200
    reason = "OK"
    will_close = False
    headers: Message


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CALIBRE_SELENIUM_HOME", str(tmp_path))
    monkeypatch.setattr(transport, "getproxies", lambda: {})
    monkeypatch.setattr(transport._state, "budget", None, raising=False)
    monkeypatch.setattr(transport._state, "http", None, raising=False)
    monkeypatch.setattr(orchestrator, "_last_rate_limit_time", 0.0)
    monkeypatch.setattr(orchestrator, "_retry_after_until", 0.0)


@pytest.fixture(params=["pooled", "proxy", "proxy-clearance", "standalone", "standalone-clearance"])
def local_http_fetch(request, monkeypatch):
    """Exercise real HTTP framing through every response-consumption path."""
    wire: List[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.connection.sendall(wire[0])
            self.close_connection = True

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    local_url = f"http://127.0.0.1:{server.server_port}/"
    real_urlopen = build_opener(ProxyHandler({})).open
    from common import common_romanceio_session as clearance

    responses = []

    def open_local(_request, timeout):
        response = real_urlopen(local_url, timeout=timeout)
        responses.append(response)
        return response

    monkeypatch.setattr(transport, "urlopen", open_local)
    monkeypatch.setattr(clearance, "open_with_clearance", open_local)
    monkeypatch.setattr(
        transport.http.client,
        "HTTPSConnection",
        lambda *_args, **kwargs: http.client.HTTPConnection("127.0.0.1", server.server_port, **kwargs),
    )
    if request.param.startswith("proxy"):
        monkeypatch.setattr(transport, "getproxies", lambda: {"https": "http://proxy.invalid"})
        monkeypatch.setattr(transport, "proxy_bypass", lambda _host: False)
    session = transport.HttpSession()

    def fetch(body, headers):
        wire[:] = [b"HTTP/1.1 200 OK\r\nConnection: close\r\n" + headers + b"\r\n" + body]
        req = Request(URL, headers={"Cookie": "cf_clearance=test"} if "clearance" in request.param else {})
        open_request = transport.open_request if request.param.startswith("standalone") else session.open
        with open_request(req, 2) as response:
            return response.read()

    try:
        yield fetch
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert all(response.closed for response in responses)


@pytest.mark.parametrize("framing", ["length", "chunked", "eof"])
def test_complete_http_bodies(local_http_fetch, framing):
    body = b'{"success":true,"books":[]}'
    headers = b""
    wire_body = body
    if framing == "length":
        headers = f"Content-Length: {len(body)}\r\n".encode()
    elif framing == "chunked":
        headers = b"Transfer-Encoding: chunked\r\n"
        wire_body = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
    assert local_http_fetch(wire_body, headers) == body


@pytest.mark.parametrize("framing", ["length", "chunked"])
def test_truncated_http_bodies_raise_incomplete_read(local_http_fetch, framing):
    # lxml can repair this prefix into a page that passes detail validation.
    body = (
        b'<div id="main"><div class="book-info"><h1>Book</h1>'
        b'<h2 class="author">Author</h2></div><div id="book-stats">'
    )
    headers = f"Content-Length: {len(body) + 10000}\r\n".encode()
    if framing == "chunked":
        headers = b"Transfer-Encoding: chunked\r\n"
        body = f"{len(body) + 10000:x}\r\n".encode() + body
    with pytest.raises(http.client.IncompleteRead):
        local_http_fetch(body, headers)


def test_http_size_limit_applies_to_all_transports(local_http_fetch, monkeypatch):
    monkeypatch.setattr(transport, "_MAX_RESPONSE_BYTES", 128)
    assert local_http_fetch(b"x" * 128, b"Content-Length: 128\r\n") == b"x" * 128
    with pytest.raises(ValueError, match="size limit"):
        local_http_fetch(b"x" * 129, b"Content-Length: 129\r\n")


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_http_budget_applies_to_all_transports(local_http_fetch, monkeypatch, stop):
    abort = threading.Event()
    budget = transport.Budget(abort)
    monkeypatch.setattr(transport._state, "budget", budget)
    original_read = http.client.HTTPResponse.read1

    def interrupted_read(response, size):
        chunk = original_read(response, size)
        if stop == "cancel":
            abort.set()
        else:
            budget.deadline = 0
        return chunk

    monkeypatch.setattr(http.client.HTTPResponse, "read1", interrupted_read)
    with pytest.raises(transport.LookupCancelled):
        local_http_fetch(b"valid body", b"Content-Length: 10\r\n")


@pytest.mark.parametrize("stop", ["cancel", "deadline", None])
def test_response_reads_update_timeout_and_observe_budget(monkeypatch, stop):
    now = [1000.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    abort = threading.Event()
    monkeypatch.setattr(transport._state, "budget", transport.Budget(abort, seconds=3))
    timeouts: List[float] = []

    class SlowResponse(Response):
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=timeouts.append)))

        def read1(self, _size=-1):
            now[0] += 1
            if stop == "cancel":
                abort.set()
            if stop == "deadline":
                now[0] += 3
            return super().read1(1)

    response = SlowResponse(b"x")
    if stop:
        with pytest.raises(transport.LookupCancelled):
            transport._read_response(response, 30)
        assert timeouts == [3]
    else:
        assert transport._read_response(response, 30) == b"x"
        assert timeouts == [3, 2]
    assert response.closed


def test_one_connection_for_job_requests_closed_on_error(monkeypatch):
    connections, requests = [], []

    class Connection:
        sock = None

        def __init__(self, *_args, **_kwargs):
            self.closed = False
            connections.append(self)

        def request(self, method, path, headers):
            requests.append((method, path, headers))

        def getresponse(self):
            response = Response(b'{"success":true,"books":[]}')
            response.status, response.reason, response.will_close = 200, "OK", False
            response.headers = Message()
            response.headers.add_header("Set-Cookie", "__cf_bm=local-test; Secure; Domain=.romance.io")
            response.headers.add_header("Set-Cookie", "login=must-not-retain; Secure")
            return response

        def close(self):
            self.closed = True

    monkeypatch.setattr(transport.http.client, "HTTPSConnection", Connection)

    @transport.job_session
    def job():
        for _ in range(2):
            assert api._make_json_request(URL) == {"success": True, "books": []}
        raise ValueError("job failed")

    with pytest.raises(ValueError, match="job failed"):
        job()
    assert len(connections) == 1 and connections[0].closed
    assert "Cookie" not in requests[0][2]
    assert "User-Agent" in requests[0][2]
    assert "User-agent" not in requests[0][2]
    assert requests[0][2]["Connection"] == "keep-alive"
    assert requests[1][2]["Cookie"] == "__cf_bm=local-test"
    assert getattr(transport._state, "http", None) is None


def test_redirect_never_forwards_session_cookie(monkeypatch):
    calls = []

    class Connection:
        sock = None

        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            calls.append(True)

        def getresponse(self):
            response = Response(b"")
            response.status, response.reason, response.will_close = 302, "Found", False
            response.headers = Message()
            response.headers["Location"] = "https://elsewhere.test/"
            return response

        def close(self):
            pass

    monkeypatch.setattr(transport.http.client, "HTTPSConnection", Connection)
    with pytest.raises(HTTPError, match="outside Romance.io"):
        transport.HttpSession().open(Request(URL, headers={"Cookie": "cf_clearance=test"}), 10)
    assert len(calls) == 1


def test_shared_budget_stops_next_browser_and_restores_context(monkeypatch):
    calls = []
    now = [100.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(request, _log, _abort):
        calls.append(request.get("backend", "embedded"))
        now[0] += 121
        raise helper.BrowserFetchError("Qt exhausted the budget")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)

    @transport.lookup_budget
    def lookup(abort=None):
        return helper.fetch_page(URL, "romanceio", abort=abort)

    with pytest.raises(helper.BrowserFetchError):
        lookup()
    assert calls == ["embedded"]
    assert transport.current_budget() is None


def test_cancelled_http_never_opens_connection(monkeypatch):
    abort = threading.Event()
    abort.set()
    monkeypatch.setattr(transport._state, "budget", transport.Budget(abort))
    monkeypatch.setattr(transport.http.client, "HTTPSConnection", lambda *_a, **_k: pytest.fail("HTTP after cancel"))
    with pytest.raises(transport.LookupCancelled):
        transport.HttpSession().open(Request(URL), 10)


def test_failed_engines_are_not_reopened_by_html_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)
    monkeypatch.setattr(transport._state, "budget", transport.Budget())

    def fail(request, _log, _abort):
        assert request.get("search_fallback_url") == "https://www.romance.io/search?q=Title"
        calls.append(request.get("backend", "embedded"))
        raise helper.BrowserFetchError("both routes failed")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fail)
    for url in (URL, "https://www.romance.io/search?q=Title"):
        with pytest.raises(helper.BrowserFetchError):
            helper.fetch_page(url, "romanceio")
    assert calls == ["embedded", "chrome"]


def test_chrome_json_404_uses_html_in_same_driver():
    urls = []
    missing = "<html>" + engine._NOT_FOUND + " " * 100 + "</html>"
    valid = '<html><ul id="book-results"><li class="has-background">Result</li></ul>' + " " * 100 + "</html>"

    class Driver:
        title = "Romance.io"
        page_source = missing

        def set_page_load_timeout(self, _timeout):
            pass

        def set_script_timeout(self, _timeout):
            pass

        def uc_open_with_reconnect(self, url, reconnect_time):
            urls.append(url)
            self.page_source = missing if len(urls) == 1 else valid

    request = {"url": URL, "search_fallback_url": "https://www.romance.io/search?q=Title", "max_wait": 5}
    assert engine.navigate_chrome(Driver(), request, lambda _msg: None) == valid
    assert urls == [URL, request["search_fallback_url"]]
    assert not engine.clearance_page_valid(missing, request)


def test_search_shell_is_not_valid_empty_result():
    shell = '<html><ul id="book-results"></ul>' + " " * 100 + "</html>"
    assert not engine.page_ready(
        shell, "Search", {"url": URL.replace("/json/search_books", "/search"), "wait_for_element": "book-results"}
    )
    assert engine.page_failure("<html>" + engine._NOT_FOUND + "</html>", {"url": URL})


def test_empty_browser_json_does_not_navigate_html():
    calls = []

    class Driver:
        title = ""
        page_source = '<html><pre>{"success":true,"books":[]}</pre>' + " " * 100 + "</html>"

        def set_page_load_timeout(self, _timeout):
            pass

        def set_script_timeout(self, _timeout):
            pass

        def uc_open_with_reconnect(self, url, reconnect_time):
            calls.append(url)

    engine.navigate_chrome(
        Driver(), {"url": URL, "search_fallback_url": "https://www.romance.io/search?q=Title"}, print
    )
    assert calls == [URL]


def test_browser_html_recovery_preserves_matching_and_metadata(monkeypatch):
    def blocked(*_args):
        raise api.JsonApiAccessDeniedError("403")

    monkeypatch.setattr(api, "_make_json_request", blocked)
    html = """<html><ul id="book-results"><li class="has-background">
    <div class="flexbox"><div class="col">
    <h3><a href="/books/5484ecd47a5936fb0405756c/pride-and-prejudice">Pride and Prejudice</a></h3>
    <h4><div><span><a>Jane Austen</a></span></div></h4>
    </div></div></li></ul></html>"""
    books = api.search_books_json("Pride and Prejudice", ["Jane Austen"], browser_fetch_func=lambda _url: html)
    from common.common_romanceio_search import find_best_json_match

    assert find_best_json_match(books, "Pride and Prejudice", ["Jane Austen"]) == "5484ecd47a5936fb0405756c"
    assert books[0]["info"]["title"] == "Pride and Prejudice"
    assert books[0]["authors"] == [{"name": "Jane Austen"}]


def test_rate_limit_waits_preserve_budget_for_browser_recovery(monkeypatch):
    now, calls = [1000.0], []
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(orchestrator, "_last_rate_limit_time", now[0])
    monkeypatch.setattr(orchestrator, "_last_json_request_time", {})
    monkeypatch.setattr(orchestrator, "_dead_json_endpoints", set())

    def slow_rate_limited_request(*_args):
        calls.append(("http", now[0]))
        now[0] += 10
        raise api.JsonApiRateLimitError("429")

    def browser(*_args):
        calls.append(("browser", now[0]))
        assert transport.remaining(120) == pytest.approx(90)
        return "matched-book"

    result = orchestrator.search_with_fallback(
        "Title", [], slow_rate_limited_request, browser, log_func=lambda _msg: None
    )
    assert result == "matched-book"
    assert calls == [("http", 1060), ("http", 1085), ("http", 1110), ("browser", 1180)]


def test_json_spacing_preserves_active_budget(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(orchestrator, "_last_rate_limit_time", 0)
    monkeypatch.setattr(orchestrator, "_last_json_request_time", {URL: now[0]})
    budget = transport.Budget(seconds=2)
    monkeypatch.setattr(transport._state, "budget", budget)
    orchestrator._throttle_json_call(lambda _msg: None, URL, abort=budget)
    assert now[0] == 1006
    assert budget.remaining(120) == pytest.approx(2)


def test_cancellation_during_rate_limit_wait_stops_all_requests(monkeypatch):
    now = [1000.0]
    abort = threading.Event()
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(orchestrator, "_last_rate_limit_time", now[0])
    monkeypatch.setattr(orchestrator, "_last_json_request_time", {})
    monkeypatch.setattr(orchestrator, "_dead_json_endpoints", set())

    def sleep(seconds):
        now[0] += seconds
        abort.set()

    monkeypatch.setattr(transport.time, "sleep", sleep)
    unexpected = lambda *_args: pytest.fail("Request started after cancellation")
    with pytest.raises(orchestrator.SearchFailedError, match="cancelled"):
        orchestrator.search_with_fallback("Title", [], unexpected, unexpected, abort=abort, log_func=lambda _msg: None)
    assert now[0] == 1000.5


def test_ordinary_retry_wait_still_consumes_active_budget(monkeypatch):
    now, calls = [1000.0], []
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    budget = transport.Budget(seconds=1)
    monkeypatch.setattr(transport._state, "budget", budget)

    def fail():
        calls.append(True)
        raise RuntimeError("Transient failure")

    result = orchestrator._retry_with_delay(fail, "HTTP", 3, 2, lambda _msg: None, abort=budget)
    assert not result.success and len(calls) == 1
    assert now[0] == 1001


def test_cancel_at_end_of_rate_limit_retry_wait_does_not_start_request(monkeypatch):
    now, calls = [1000.0], []
    abort = threading.Event()
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(orchestrator, "_last_rate_limit_time", 0)
    budget = transport.Budget(abort)
    monkeypatch.setattr(transport._state, "budget", budget)

    def sleep(seconds):
        now[0] += seconds
        if now[0] >= 1015:
            abort.set()

    def fail():
        calls.append(True)
        raise api.JsonApiRateLimitError("429")

    monkeypatch.setattr(transport.time, "sleep", sleep)
    result = orchestrator._retry_with_delay(fail, "JSON", 3, 2, lambda _msg: None, abort=budget)
    assert not result.success and len(calls) == 1
    assert now[0] == 1015


def test_job_remembers_403_per_endpoint_until_new_clearance(monkeypatch):
    requests = []

    def network(_session, request, _timeout):
        requests.append(request.full_url)
        if "/json/search_books" in request.full_url and request.get_header("Cookie") != "cf_clearance=renewed":
            raise HTTPError(request.full_url, 403, "Forbidden", Message(), None)
        return io.BytesIO(b'{"success":true,"books":[]}')

    monkeypatch.setattr(transport.HttpSession, "_open", network)

    @transport.job_session
    def job():
        for title in ("first", "second"):
            with pytest.raises(api.JsonApiAccessDeniedError):
                api._make_json_request(URL + title)
        assert len(requests) == 1
        api._make_json_request("https://www.romance.io/json/books/book-id")
        api._make_json_request("https://www.romance.io/books/book-id")
        assert len(requests) == 3
        # New valid clearance enables the previously rejected endpoint.
        from common.common_romanceio_session import save_clearance

        assert save_clearance(
            [
                {
                    "name": "cf_clearance",
                    "value": "renewed",
                    "domain": ".romance.io",
                    "expiry": transport.time.time() + 600,
                }
            ],
            "Browser agent",
        )
        assert api._make_json_request(URL) == {"success": True, "books": []}
        assert len(requests) == 4

    job()
    # A new job starts with no negative cache, even without browser clearance.
    monkeypatch.setattr(api, "clearance_headers", lambda _url: {})
    with pytest.raises(api.JsonApiAccessDeniedError):
        transport.job_session(api._make_json_request)(URL)
    assert len(requests) == 5


def test_removing_rejected_cookie_does_not_reset_endpoint_failure(monkeypatch):
    requests = []

    def blocked(_session, request, _timeout):
        requests.append(request.full_url)
        raise HTTPError(request.full_url, 403, "Forbidden", Message(), None)

    monkeypatch.setattr(transport.HttpSession, "_open", blocked)
    session = transport.HttpSession()
    for headers in ({"Cookie": "cf_clearance=rejected"}, {}, {}):
        with pytest.raises(HTTPError):
            session.open(Request(URL, headers=headers), 10)
    assert len(requests) == 1
    with pytest.raises(HTTPError):
        session.open(Request(URL, headers={"Cookie": "cf_clearance=different"}), 10)
    assert len(requests) == 2


@pytest.mark.parametrize("backend", ["chrome", "embedded"])
def test_explicit_backend_does_not_start_the_other_browser(monkeypatch, backend):
    calls = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fail(request, _log, _abort):
        calls.append(request["backend"])
        raise helper.BrowserFetchError("Unavailable")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fail)
    with pytest.raises(helper.BrowserFetchError):
        helper.fetch_page(URL, "romanceio", backend=backend)
    assert calls == [backend]


@pytest.mark.parametrize("success", ["chrome", "http", "embedded", "json"])
def test_chrome_first_details_try_http_before_qt(monkeypatch, success):
    calls = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)
    monkeypatch.setattr(orchestrator, "_last_rate_limit_time", 0)
    monkeypatch.setattr(orchestrator, "_last_json_request_time", {})
    monkeypatch.setattr(orchestrator, "_dead_json_endpoints", set())

    def attempt(method):
        calls.append(method)
        if method != success:
            raise helper.BrowserFetchError("Simulated failure")
        return "validated details"

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", lambda req, _log, _abort: attempt(req["backend"]))
    result = orchestrator.fetch_details_with_fallback(
        "book-id",
        json_fetch_func=lambda *_args: attempt("json"),
        lightweight_html_fetch_func=lambda *_args: attempt("http"),
        html_fetch_func=lambda *_args: helper.fetch_page(URL, "romanceio", backend="embedded"),
        chrome_fetch_func=lambda *_args: helper.fetch_page(URL, "romanceio", backend="chrome"),
        prefer_chrome=True,
        log_func=lambda _msg: None,
    )
    assert result == "validated details"
    order = ["chrome", "http", "embedded", "json"]
    assert calls == order[: order.index(success) + 1]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("120", 120),
        ("0", 0),
        (" 25 ", 25),
        (None, None),
        ("", None),
        ("-1", None),
        ("1.5", None),
        ("nan", None),
        ("inf", None),
        ("9" * 400, None),
        ("Thu, 01 Jan 1970 00:18:40 GMT", 120),
        ("Thursday, 01-Jan-70 00:18:40 GMT", 120),
        ("Thu Jan  1 00:18:40 1970", 120),
        ("Thu, 01 Jan 1970 00:00:00 GMT", 0),
    ],
)
def test_retry_after_seconds_and_http_dates(monkeypatch, value, expected):
    monkeypatch.setattr(transport.time, "time", lambda: 1000)
    assert transport.parse_retry_after(value) == expected


@pytest.mark.parametrize("route", ["search", "details"])
@pytest.mark.parametrize("retry_after", [None, "10", "120", "date", "malformed"])
def test_http_429_retries_and_browser_fallback_respect_server_wait(monkeypatch, route, retry_after):
    now, calls = [1000.0], []
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(orchestrator, "_last_json_request_time", {})
    monkeypatch.setattr(orchestrator, "_dead_json_endpoints", set())

    def blocked(request, _timeout):
        calls.append(("http", now[0] - 1000))
        headers = Message()
        if retry_after is not None:
            headers["Retry-After"] = formatdate(now[0] + 120, usegmt=True) if retry_after == "date" else retry_after
        raise HTTPError(request.full_url, 429, "Too Many Requests", headers, None)

    def browser(*_args):
        calls.append(("browser", now[0] - 1000))
        assert transport.remaining(120) == pytest.approx(120)
        return "result"

    monkeypatch.setattr(api, "open_request", blocked)
    monkeypatch.setattr(transport, "open_request", blocked)
    if route == "search":
        result = orchestrator.search_with_fallback(
            "Title",
            [],
            lambda title, authors, log: api.search_books_json(title, authors, log_func=log),
            browser,
            log_func=lambda _msg: None,
        )
    else:
        result = orchestrator.fetch_details_with_fallback(
            "book-id",
            lambda *_args: pytest.fail("JSON should not be reached"),
            browser,
            lightweight_html_fetch_func=lambda book, log: helper.fetch_book_page_http(book, log),
            log_func=lambda _msg: None,
        )
    wait = 120 if retry_after in ("120", "date") else 15
    assert calls == [("http", 0), ("http", wait), ("http", 2 * wait), ("browser", 2 * wait + max(60, wait))]
    assert result == "result"
    assert not orchestrator._dead_json_endpoints


@pytest.mark.parametrize("cancel", [False, True])
def test_browser_entry_honors_outstanding_rate_limit_before_startup(monkeypatch, cancel):
    now, calls = [1000.0], []
    abort = threading.Event()
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)
    monkeypatch.setattr(transport._state, "budget", transport.Budget(abort))
    orchestrator._record_rate_limit(transport.HttpRateLimitError("429", "120"))

    def sleep(seconds):
        now[0] += seconds
        if cancel:
            abort.set()

    def browser(request, _log, _abort):
        calls.append((request["backend"], now[0]))
        assert transport.remaining(120) == pytest.approx(120)
        return "page"

    monkeypatch.setattr(transport.time, "sleep", sleep)
    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", browser)
    if cancel:
        with pytest.raises(helper.BrowserFetchError, match="cancelled"):
            helper.fetch_page(URL, "romanceio")
        assert calls == [] and now[0] == 1000.5
    else:
        assert helper.fetch_page(URL, "romanceio") == "page"
        assert calls == [("embedded", 1120)]


def test_429_is_not_cached_as_access_denied(monkeypatch):
    calls = []

    def blocked(_session, request, _timeout):
        calls.append(True)
        raise HTTPError(request.full_url, 429, "Too Many Requests", Message(), None)

    monkeypatch.setattr(transport.HttpSession, "_open", blocked)
    session = transport.HttpSession()
    for _ in range(2):
        with pytest.raises(HTTPError) as error:
            session.open(Request(URL), 10)
        assert error.value.code == 429
    assert len(calls) == 2 and not session.denied_endpoints


def test_wait_observes_a_later_server_deadline_from_another_lookup(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport._state, "budget", transport.Budget())
    orchestrator._record_rate_limit(transport.HttpRateLimitError("429", "120"))

    def sleep(seconds):
        now[0] += seconds
        if now[0] == 1000.5:
            orchestrator._record_rate_limit(transport.HttpRateLimitError("429", "150"))

    monkeypatch.setattr(transport.time, "sleep", sleep)
    assert orchestrator.wait_for_rate_limit(lambda _msg: None)
    assert now[0] == 1150.5
    assert transport.remaining(120) == pytest.approx(120)


@pytest.mark.parametrize("route", ["search", "details"])
def test_429_without_headers_preserves_clearance(monkeypatch, route):
    from common.common_romanceio_session import save_clearance, clearance_headers

    assert save_clearance(
        [{"name": "cf_clearance", "value": "valid", "domain": ".romance.io", "expiry": transport.time.time() + 600}],
        "Browser agent",
    )
    original = clearance_headers(URL)

    def blocked(request, _timeout):
        # Exercise an opener that supplies no response headers.
        raise HTTPError(request.full_url, 429, "Too Many Requests", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(api, "open_request", blocked)
    monkeypatch.setattr(transport, "open_request", blocked)
    with pytest.raises(transport.HttpRateLimitError) as error:
        if route == "search":
            api.search_books_json("Title")
        else:
            helper.fetch_book_page_http("book-id")
    assert error.value.retry_after is None
    assert clearance_headers(URL) == original


def test_book_html_429_cooldown_applies_to_the_next_book(monkeypatch):
    now, calls = [1000.0], []
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    def network(request, _timeout):
        calls.append(now[0] - 1000)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, "Too Many Requests", Message(), None)
        return io.BytesIO(b'<html><div id="book-stats">Ratings</div></html>')

    monkeypatch.setattr(transport, "open_request", network)
    unexpected = lambda *_args: pytest.fail("Successful HTTP should not require fallback")
    for book in ("first", "second"):
        result = orchestrator.fetch_details_with_fallback(
            book,
            unexpected,
            unexpected,
            lightweight_html_fetch_func=lambda book_id, log: helper.fetch_book_page_http(book_id, log),
            log_func=lambda _msg: None,
        )
        assert result is not None
        assert result[1] is True
    assert calls == [0, 15, 60]
