"""Validate readiness without importing Qt or opening a browser."""

from typing import List

import pytest
from common.common_romanceio_webengine import page_ready


def document(body):
    return "<html><head></head><body>" + body + "<!--" + " " * 100 + "--></body></html>"


def test_json_waits_for_actual_payload():
    request = {"url": "https://www.romance.io/json/search_books?search=test"}
    assert not page_ready(document("<pre>Checking your browser</pre>"), "Just a moment...", request)
    assert not page_ready(document('<pre>{"success":</pre>'), "", request)
    assert page_ready(document('<pre>{"success":true,"books":[]}</pre>'), "", request)
    assert not page_ready(document('<pre>{"success":false}</pre>'), "", request)


@pytest.mark.parametrize("marker,expected", [("book-stats", True), ("unrelated", False)])
def test_html_requires_expected_content(marker, expected):
    request = {"url": "https://www.romance.io/books/test", "wait_for_element": "book-stats"}
    assert page_ready(document(marker), "Book", request) is expected
    assert not page_ready(document(marker), "Just a moment...", request)


def test_not_found_completes_without_expected_element():
    request = {
        "url": "https://www.romance.io/books/test",
        "wait_for_element": "book-stats",
        "not_found_marker": "not found",
    }
    assert page_ready(document("NOT FOUND"), "Missing book", request)


def test_optional_chrome_fallback_order(monkeypatch):
    from common import common_romanceio_fetch_helper as helper

    calls = []
    logs: List[str] = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(request, log, abort):
        calls.append(request.get("backend", "embedded"))
        if calls[-1] == "embedded":
            raise helper.BrowserFetchError("Challenge could not be cleared")
        return "Chrome page"

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    assert helper.fetch_page("https://www.romance.io", "romanceio", log_func=logs.append) == "Chrome page"
    assert calls == ["embedded", "chrome"]
    assert "Embedded browser failed: Challenge could not be cleared" in logs


@pytest.mark.parametrize("outcome", ["disabled", "cancelled", "success", "chrome-fails"])
def test_chrome_does_not_launch_unnecessarily_or_repeat(monkeypatch, outcome):
    import threading
    from common import common_romanceio_fetch_helper as helper

    calls = []
    abort = threading.Event()
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(request, log, event):
        calls.append(request.get("backend", "embedded"))
        if outcome == "success":
            return "Valid empty results or not-found page"
        if outcome == "cancelled":
            abort.set()
        raise helper.BrowserFetchError("Failed")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    if outcome == "success":
        helper.fetch_page("https://www.romance.io", "romanceio", abort=abort, allow_chrome_fallback=True)
    else:
        with pytest.raises(helper.BrowserFetchError):
            helper.fetch_page(
                "https://www.romance.io", "romanceio", abort=abort, allow_chrome_fallback=outcome != "disabled"
            )
    assert calls == (["embedded", "chrome"] if outcome == "chrome-fails" else ["embedded"])


def test_existing_chrome_first_preference(monkeypatch):
    from common import common_romanceio_fetch_helper as helper

    calls = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(request, log, abort):
        calls.append(request.get("backend", "embedded"))
        if calls[-1] == "chrome":
            raise helper.BrowserFetchError("Chrome unavailable")
        return "Rendered details"

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    assert helper.fetch_page("https://www.romance.io", "romanceio", prefer_chrome=True) == "Rendered details"
    assert calls == ["chrome", "embedded"]
