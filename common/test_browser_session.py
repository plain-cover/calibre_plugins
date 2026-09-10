"""Clearance reuse, expiry, and origin confinement without network or Chrome."""

import io
import json
import os
import time
from email.message import Message
from http.client import HTTPMessage
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from common import common_romanceio_session as session
from common import common_romanceio_json_api as api
from common import common_romanceio_fetch_helper as helper

URL = "https://www.romance.io/json/search_books?search=Title"
AGENT = "Mozilla/5.0 Test Chrome/152.0.0.0"


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("CALIBRE_SELENIUM_HOME", str(tmp_path))


def save(value="test-clearance", expiry=None):
    return session.save_clearance(
        [
            {"name": "login", "domain": ".romance.io", "value": "must-not-save", "expiry": time.time() + 3600},
            {
                "name": "cf_clearance",
                "domain": ".romance.io",
                "value": value,
                "expiry": expiry if expiry is not None else time.time() + 3600,
            },
        ],
        AGENT,
    )


def test_private_cache_saves_only_clearance_and_caps_expiry():
    assert save()
    path = Path(session._cache_path())
    record = json.loads(path.read_text())
    assert set(record) == {"value", "user_agent", "expires"}
    assert "must-not-save" not in path.read_text()
    assert time.time() < record["expires"] <= time.time() + 1800
    assert session.clearance_headers(URL) == {"Cookie": "cf_clearance=test-clearance", "User-Agent": AGENT}
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://www.romance.io/",
        "https://romance.io.evil.test/",
        "https://other.test/",
        "https://www.romance.io:8443/",
        "https://user@www.romance.io/",
        "file:///tmp/book",
    ],
)
def test_clearance_never_attaches_outside_exact_https_origin(url):
    save()
    assert session.clearance_headers(url) == {}


@pytest.mark.parametrize("value", ["bad; injected=value", "bad\r\nHeader: value", 'bad"cookie', ""])
def test_invalid_cookie_values_are_not_cached(value):
    assert not save(value)
    assert not session.clearance_headers(URL)


def test_expired_corrupt_and_oversized_cache_are_ignored():
    path = Path(session._cache_path())
    for content in ("not json", "x" * 9000, json.dumps({"value": "test", "user_agent": AGENT, "expires": 1})):
        path.write_text(content)
        assert session.clearance_headers(URL) == {}
    assert not save(expiry=time.time() - 1)


def test_rejected_clearance_does_not_erase_newer_clearance():
    save("new-value")
    session.discard_clearance("cf_clearance=old-value")
    assert session.clearance_headers(URL)["Cookie"] == "cf_clearance=new-value"
    session.discard_clearance("cf_clearance=new-value")
    assert session.clearance_headers(URL) == {}


@pytest.mark.parametrize("target", ["https://other.test/", "http://www.romance.io/", "https://www.romance.io:8443/"])
def test_redirect_cannot_forward_clearance_to_another_origin(target):
    request = Request(URL, headers={"Cookie": "cf_clearance=test"})
    handler = session._ClearanceRedirectHandler()
    body = io.BytesIO()
    headers = HTTPMessage()
    with pytest.raises(HTTPError):
        handler.redirect_request(request, body, 302, "Found", headers, target)
    same_origin = handler.redirect_request(request, body, 302, "Found", headers, "https://www.romance.io/books/id/")
    assert same_origin is not None
    assert same_origin.get_header("Cookie") == "cf_clearance=test"


def test_first_search_bootstraps_clearance_and_next_search_uses_http(monkeypatch):
    events = []

    def blocked(request, **_kwargs):
        events.append("plain-http")
        raise HTTPError(request.full_url, 403, "Forbidden", Message(), None)

    def browser(_url):
        events.append("browser")
        save()
        return '<pre>{"success":true,"books":[]}</pre>'

    def cleared(request, _timeout):
        events.append("cleared-http")
        assert request.get_header("Cookie") == "cf_clearance=test-clearance"
        assert request.get_header("User-agent") == AGENT
        return io.BytesIO(b'{"success":true,"books":[]}')

    def dispatch(request, timeout):
        return cleared(request, timeout) if request.has_header("Cookie") else blocked(request)

    monkeypatch.setattr(api, "open_request", dispatch)
    for _ in range(2):
        assert api.search_books_json("Title", browser_fetch_func=browser) == []
    assert events == ["plain-http", "browser", "cleared-http"]


def test_rejected_cached_clearance_is_removed_before_browser_renewal(monkeypatch):
    save()

    def rejected(request, _timeout):
        raise HTTPError(request.full_url, 403, "Forbidden", Message(), None)

    def browser(_url):
        assert session.clearance_headers(URL) == {}
        save("renewed")
        return '<pre>{"success":true,"books":[]}</pre>'

    monkeypatch.setattr(api, "open_request", rejected)
    assert api.search_books_json("Title", browser_fetch_func=browser) == []
    assert session.clearance_headers(URL)["Cookie"] == "cf_clearance=renewed"


def test_book_page_http_reuses_clearance_from_search(monkeypatch):
    save()
    calls = []

    def open_request(request, _timeout):
        calls.append(request.get_header("Cookie"))
        return io.BytesIO(b'<html><div id="book-stats">Rating</div></html>')

    from common import common_romanceio_transport as transport

    monkeypatch.setattr(transport, "open_request", open_request)
    page, valid = helper.fetch_book_page_http("book-id")
    assert valid and "book-stats" in page
    assert calls == ["cf_clearance=test-clearance"]
