"""Validate readiness without importing Qt or opening a browser."""

import json
import os
import time
from typing import Any, Dict, List

import pytest
from common.common_romanceio_webengine import page_ready


@pytest.fixture(autouse=True)
def isolated_session(monkeypatch, tmp_path):
    # Lookups remember Romance.io's check outside the test's own files otherwise.
    monkeypatch.setenv("CALIBRE_SELENIUM_HOME", str(tmp_path / "session"))


@pytest.mark.parametrize("existing_flags", ("", "--disable-logging"))
def test_embedded_worker_disables_gpu_before_importing_qt(monkeypatch, existing_flags):
    import builtins
    import os
    from common.common_romanceio_webengine import fetch_page

    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", existing_flags)
    original_import = builtins.__import__

    class QtImportReached(Exception):
        pass

    def checked_import(name, *args, **kwargs):
        if name == "calibre.gui2":
            flags = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split()
            assert "--disable-gpu" in flags
            assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in flags
            assert "--disable-quic" in flags
            assert set(existing_flags.split()).issubset(flags)
            assert "--no-sandbox" not in flags
            raise QtImportReached()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    with pytest.raises(QtImportReached):
        fetch_page({"url": "http://127.0.0.1/fixture"}, lambda _message: None)


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


@pytest.mark.parametrize(
    "failures,hinted",
    [
        # A slow page is not Cloudflare's check; the browsers say when they see one.
        (["Embedded web engine timed out waiting for validated content or Cloudflare clearance"] * 2, False),
        (["Chrome verification challenge did not clear within its navigation budget", "Failed"], True),
        (["Browser worker failed", "Browser worker failed"], False),
    ],
)
def test_verification_hint_follows_challenge_failures(monkeypatch, failures, hinted):
    from common import common_romanceio_fetch_helper as helper
    from common.common_romanceio_session import VERIFY_HINT

    logs: List[str] = []
    remaining = list(failures)
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(_request, _log, _abort):
        raise helper.BrowserFetchError(remaining.pop(0))

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    with pytest.raises(helper.BrowserFetchError):
        helper.fetch_page("https://www.romance.io", "romanceio", log_func=logs.append)
    assert logs.count(VERIFY_HINT) == (1 if hinted else 0)


def test_verification_hint_follows_a_challenge_seen_before_cancellation(monkeypatch):
    from common import common_romanceio_fetch_helper as helper
    from common.common_romanceio_session import CHALLENGE_SEEN, VERIFY_HINT

    logs: List[str] = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(_request, log, _abort):
        log(CHALLENGE_SEEN)
        raise helper.BrowserFetchError("Browser exceeded its 45s total time limit (including startup/navigation/quit)")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    with pytest.raises(helper.BrowserFetchError):
        helper.fetch_page("https://www.romance.io", "romanceio", log_func=logs.append)
    assert logs.count(VERIFY_HINT) == 1


@pytest.mark.parametrize(
    "max_wait,worker_timeout,backend,expected",
    [
        (60, 45, "embedded", 35),
        (30, 45, "embedded", 30),
        (60, 65.4, "chrome", 45.4),
        (60, 90, "chrome", 60),
        (60, 5, "embedded", 1),
    ],
)
def test_navigation_fits_inside_the_worker_time_limit(max_wait, worker_timeout, backend, expected):
    from common import common_romanceio_fetch_helper as helper

    assert helper._navigation_budget(max_wait, worker_timeout, backend) == pytest.approx(expected)


def test_verification_hint_is_not_logged_when_a_later_browser_succeeds(monkeypatch):
    from common import common_romanceio_fetch_helper as helper
    from common.common_romanceio_session import VERIFY_HINT

    logs: List[str] = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(request, _log, _abort):
        if request["backend"] == "embedded":
            raise helper.BrowserFetchError(
                "Embedded web engine timed out waiting for validated content or Cloudflare clearance"
            )
        return "Chrome page"

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    assert helper.fetch_page("https://www.romance.io", "romanceio", log_func=logs.append) == "Chrome page"
    assert VERIFY_HINT not in logs


class _FakeCdp:
    """Serve Cloudflare's check until a condition clears it, recording calls."""

    def __init__(self, cleared_by):
        self.cleared_by = cleared_by
        self.calls: List[str] = []

    def _cleared(self):
        return self.cleared_by(self.calls)

    def get_page_source(self, include_shadow_dom=False):
        return document("book-stats" if self._cleared() else "challenge")

    def get_title(self):
        self.calls.append("poll")
        return "Book" if self._cleared() else "Just a moment..."

    def evaluate(self, _script):
        return "Chrome-UA"

    def __getattr__(self, name):
        return lambda *_args, **_kwargs: self.calls.append(name)


class _FakeChrome:
    def __init__(self, cleared_by):
        self.cdp = _FakeCdp(cleared_by)

    def uc_activate_cdp_mode(self, _url):
        self.cdp.calls.append("open")


@pytest.fixture
def chrome_session(monkeypatch, tmp_path):
    from common import common_romanceio_session as session
    from common import common_romanceio_webengine as webengine

    monkeypatch.setenv("CALIBRE_SELENIUM_HOME", str(tmp_path))
    monkeypatch.setattr(webengine, "_CHROME_CHALLENGE_WAIT_SECONDS", 0)
    injected: List[str] = []
    monkeypatch.setattr(
        webengine, "set_chrome_clearance", lambda _driver, clearance: injected.append(clearance["value"])
    )

    def save(user_agent):
        cookie = {"name": "cf_clearance", "value": "saved", "domain": ".romance.io", "expiry": time.time() + 3600}
        assert session.save_clearance([cookie], user_agent)

    return webengine, session, injected, save


BOOK_REQUEST = {"url": "https://www.romance.io/books/test", "wait_for_element": "book-stats", "max_wait": 1.5}


def test_chrome_stops_soon_after_automatic_check_handling_fails(chrome_session, monkeypatch):
    webengine, _session, _injected, _save = chrome_session
    monkeypatch.setattr(webengine, "_CHROME_CHALLENGE_SETTLE_SECONDS", 0)
    driver = _FakeChrome(lambda _calls: False)
    started = time.monotonic()

    with pytest.raises(Exception, match="verification challenge"):
        webengine.navigate_chrome(driver, {**BOOK_REQUEST, "max_wait": 60}, lambda _message: None)
    assert driver.cdp.calls.count("solve_captcha") == 2
    assert time.monotonic() - started < 10


@pytest.mark.parametrize("http_challenged,expected", [(True, ["chrome"]), (False, ["embedded", "chrome"])])
def test_lookup_goes_straight_to_chrome_after_http_meets_the_check(monkeypatch, http_challenged, expected):
    from common import common_romanceio_fetch_helper as helper
    from common import common_romanceio_transport as transport
    from common.common_romanceio_session import CHALLENGE_SEEN

    budget = transport.Budget()
    budget.http_challenged = http_challenged
    monkeypatch.setattr(transport._state, "budget", budget, raising=False)
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)
    calls: List[str] = []

    def fetch(request, log, _abort):
        calls.append(request["backend"])
        log(CHALLENGE_SEEN)
        raise helper.BrowserFetchError("Chrome verification challenge did not clear within its navigation budget")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    with pytest.raises(helper.BrowserFetchError):
        helper.fetch_page("https://www.romance.io/books/test", "romanceio", log_func=lambda _message: None)
    assert calls == expected


def _http_challenged_lookup(monkeypatch, outcome):
    """Run one browser lookup after HTTP met the check; outcome fakes each browser."""
    from common import common_romanceio_fetch_helper as helper
    from common import common_romanceio_transport as transport

    budget = transport.Budget()
    budget.http_challenged = True
    monkeypatch.setattr(transport._state, "budget", budget, raising=False)
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)
    calls: List[str] = []
    logs: List[str] = []

    def fetch(request, _log, _abort):
        calls.append(request["backend"])
        return outcome(request["backend"])

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    try:
        page = helper.fetch_page("https://www.romance.io/books/test", "romanceio", log_func=logs.append)
    except helper.BrowserFetchError:
        page = None
    return page, calls, logs


def _save_chrome_clearance():
    from common import common_romanceio_session as session

    cookie = {"name": "cf_clearance", "value": "earned", "domain": ".romance.io", "expiry": time.time() + 3600}
    assert session.save_clearance([cookie], "Chrome-UA")


def test_chrome_timing_out_before_the_check_appears_still_skips_embedded(monkeypatch):
    from common import common_romanceio_fetch_helper as helper
    from common import common_romanceio_session as session

    def timed_out(_backend):
        raise helper.BrowserFetchError("Chrome did not return validated content within its navigation budget")

    page, calls, logs = _http_challenged_lookup(monkeypatch, timed_out)
    assert page is None
    assert calls == ["chrome"]
    assert session.VERIFY_HINT in logs
    assert session.automatic_check_paused()


def test_lookup_asks_for_verification_at_once_after_automatic_handling_failed(monkeypatch):
    from common import common_romanceio_session as session

    session.note_automatic_check_failed()
    page, calls, logs = _http_challenged_lookup(monkeypatch, lambda _backend: "Rendered")
    assert page is None
    assert calls == []
    assert session.VERIFY_HINT in logs


def test_automatic_handling_resumes_after_an_hour(monkeypatch):
    from common import common_romanceio_session as session

    now = [1_000_000.0]
    monkeypatch.setattr(session.time, "time", lambda: now[0])
    session.note_automatic_check_failed()
    now[0] += 59 * 60
    assert session.automatic_check_paused()
    now[0] += 2 * 60
    assert not session.automatic_check_paused()


def test_saved_verification_resumes_automatic_handling(monkeypatch):
    from common import common_romanceio_session as session

    session.note_automatic_check_failed()
    _save_chrome_clearance()
    assert not session.automatic_check_paused()
    page, calls, _logs = _http_challenged_lookup(monkeypatch, lambda _backend: "Rendered")
    assert (page, calls) == ("Rendered", ["chrome"])


class _FakeResponse:
    def __init__(self, body, content_type="text/html; charset=utf-8"):
        self.body = body.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class _FakeCamoufox:
    """Serve each answer in turn; Cloudflare hands over clearance after some cookie polls."""

    def __init__(self, answers, clearance_after_polls=None):
        self.answers = list(answers)
        self.clearance_after_polls = clearance_after_polls
        self.polls = 0
        self.opened: List[str] = []
        self.cookies_set: List[str] = []
        self.closed = False

    def user_agent(self):
        return "Camoufox-UA"

    def set_simple_cookie(self, name, value, domain=None):
        assert (name, domain) == ("cf_clearance", ".romance.io")
        self.cookies_set.append(value)

    def cookies(self):
        self.polls += 1
        if self.clearance_after_polls is not None and self.polls > self.clearance_after_polls:
            return [
                {"name": "cf_clearance", "value": "camoufox", "domain": ".romance.io", "expires": time.time() + 3600}
            ]
        return []

    def open(self, url, timeout=None):
        from urllib.error import URLError

        assert timeout and timeout > 0
        self.opened.append(url)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, int):
            error = URLError(f"HTTP {answer}")
            setattr(error, "code", answer)
            raise error
        return answer

    def shutdown(self):
        self.closed = True


@pytest.fixture
def camoufox(monkeypatch):
    """Run the Camoufox backend against a fake browser, on a fake clock."""
    from types import SimpleNamespace
    from common import common_romanceio_camoufox as module

    now = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(module, "installed_camoufox", lambda: SimpleNamespace(version="test", path="camoufox"))
    logs: List[str] = []

    def run(browser, request):
        return module.fetch_page_with_camoufox(request, logs.append, browser_factory=lambda _install: browser)

    return run, logs, now


CAMOUFOX_BOOK = {
    "url": "https://www.romance.io/books/test",
    "wait_for_element": "book-stats",
    "search_fallback_url": "https://www.romance.io/search?q=test",
    "max_wait": 60,
}


def test_camoufox_loads_only_the_requested_page(camoufox):
    run, _logs, _now = camoufox
    browser = _FakeCamoufox([_FakeResponse(document("book-stats"))])

    assert "book-stats" in run(browser, CAMOUFOX_BOOK)
    # No warmup visits to other sites, and the browser is shut down.
    assert browser.opened == [CAMOUFOX_BOOK["url"]]
    assert browser.closed


def test_camoufox_waits_on_the_check_then_loads_the_page_once_more(camoufox):
    from common import common_romanceio_session as session

    run, logs, _now = camoufox
    browser = _FakeCamoufox([403, _FakeResponse(document("book-stats"))], clearance_after_polls=3)

    assert "book-stats" in run(browser, CAMOUFOX_BOOK)
    assert browser.opened == [CAMOUFOX_BOOK["url"]] * 2
    assert session.CHALLENGE_SEEN in logs
    # Later lookups reuse it over plain HTTP, under Camoufox's own User-Agent.
    assert session.browser_clearance("Camoufox-UA")["value"] == "camoufox"


def test_camoufox_stops_when_cloudflare_never_hands_over_clearance(camoufox):
    from common import common_romanceio_fetch_helper as helper

    run, logs, now = camoufox
    browser = _FakeCamoufox([403])
    started = now[0]

    with pytest.raises(helper.BrowserFetchError, match="verification challenge"):
        run(browser, CAMOUFOX_BOOK)
    # One load, then the rest of its budget on the check, keeping time to load
    # the page again, and no second route into the same check.
    assert browser.opened == [CAMOUFOX_BOOK["url"]]
    assert 50 <= now[0] - started <= CAMOUFOX_BOOK["max_wait"]
    assert any("Still on Cloudflare's check" in message for message in logs)
    assert browser.closed


@pytest.mark.parametrize("answers", ([_FakeResponse(document("book-stats"))], [403]))
def test_camoufox_hands_over_its_result_before_shutting_down(camoufox, answers):
    from common import common_romanceio_camoufox as module

    _run, _logs, _now = camoufox
    browser = _FakeCamoufox(answers)
    handed_over = []

    def on_done(page=None, error=None):
        assert not browser.closed
        handed_over.append((page, error))

    try:
        page = module.fetch_page_with_camoufox(CAMOUFOX_BOOK, print, lambda _install: browser, on_done)
    except Exception as error:  # pylint: disable=broad-except
        assert handed_over == [(None, error)]
    else:
        assert handed_over == [(page, None)]
    assert browser.closed


def test_camoufox_navigation_gets_its_whole_budget():
    from common import common_romanceio_fetch_helper as helper

    # A search asks for 30 seconds to render; Camoufox needs about 17 to start.
    assert helper._navigation_budget(30, 90, "camoufox") == 70
    assert helper._navigation_budget(30, 90, "chrome") == 30


def test_camoufox_hands_back_json_the_way_chrome_does(camoufox):
    run, _logs, _now = camoufox
    request = {"url": "https://www.romance.io/json/search_books?search=test", "max_wait": 30}
    browser = _FakeCamoufox([_FakeResponse('{"success":true,"books":[]}', "application/json")])

    page = run(browser, request)
    # Parsed the way callers parse Chrome's rendering of JSON.
    from common.common_romanceio_webengine import _JsonText

    parser = _JsonText()
    parser.feed(page)
    assert "".join(parser.parts) == '{"success":true,"books":[]}'


def test_camoufox_reports_a_missing_book_the_way_callers_detect_it(camoufox):
    run, _logs, _now = camoufox
    marker = "the page you are looking for can't be found"
    browser = _FakeCamoufox([404])

    page = run(browser, {**CAMOUFOX_BOOK, "not_found_marker": marker})
    assert marker in page.lower()
    assert browser.opened == [CAMOUFOX_BOOK["url"]]


def test_camoufox_moves_to_the_search_route_when_json_is_missing(camoufox):
    run, _logs, _now = camoufox
    request = {
        "url": "https://www.romance.io/json/search_books?search=test",
        "search_fallback_url": "https://www.romance.io/search?q=test",
        "max_wait": 30,
    }
    results = document('<ul id="book-results"><li class="has-background">Book</li></ul>')
    browser = _FakeCamoufox([404, _FakeResponse(results)])

    assert "book-results" in run(browser, request)
    assert browser.opened == [request["url"], request["search_fallback_url"]]


def test_camoufox_reuses_clearance_it_earned(camoufox):
    from common import common_romanceio_session as session

    run, _logs, _now = camoufox
    cookie = {"name": "cf_clearance", "value": "saved", "domain": ".romance.io", "expiry": time.time() + 3600}
    assert session.save_clearance([cookie], "Camoufox-UA")
    browser = _FakeCamoufox([_FakeResponse(document("book-stats"))])

    run(browser, CAMOUFOX_BOOK)
    assert browser.cookies_set == ["saved"]


def test_camoufox_is_used_only_when_calibre_has_installed_it(monkeypatch):
    from common import common_romanceio_camoufox as module
    from common import common_romanceio_fetch_helper as helper

    # Outside calibre 9.16+ there is no calibre.web.automate to find it with.
    assert not module.camoufox_available()
    monkeypatch.setattr(module, "installed_camoufox", lambda: None)
    with pytest.raises(helper.BrowserFetchError, match="not installed"):
        module.fetch_page_with_camoufox(CAMOUFOX_BOOK, print, browser_factory=lambda _install: pytest.fail("launched"))


def test_lookup_says_how_to_get_camoufox_when_it_is_missing(monkeypatch):
    def challenged(backend):
        from common import common_romanceio_fetch_helper as helper

        raise helper.BrowserFetchError(f"{backend} verification challenge did not clear within its navigation budget")

    _page, calls, logs = _http_challenged_lookup(monkeypatch, challenged)
    assert calls == ["chrome"]
    assert sum("Camoufox" in message for message in logs) == 1


@pytest.mark.parametrize(
    "outcomes,expected_calls,paused",
    [
        ({"camoufox": "Rendered"}, ["camoufox"], False),
        # Camoufox had the whole lookup on the check; Chrome would meet the same one.
        ({"camoufox": "challenged"}, ["camoufox"], True),
        # Chrome is the fallback for a Camoufox that could not run.
        ({"camoufox": "crashed", "chrome": "Rendered"}, ["camoufox", "chrome"], False),
        ({"camoufox": "crashed", "chrome": "challenged"}, ["camoufox", "chrome"], True),
    ],
)
def test_lookup_tries_camoufox_before_chrome_after_http_meets_the_check(monkeypatch, outcomes, expected_calls, paused):
    from common import common_romanceio_camoufox as module
    from common import common_romanceio_fetch_helper as helper
    from common import common_romanceio_session as session

    monkeypatch.setattr(module, "camoufox_available", lambda: True)

    def outcome(backend):
        if outcomes[backend] == "challenged":
            raise helper.BrowserFetchError(
                f"{backend} verification challenge did not clear within its navigation budget"
            )
        if outcomes[backend] == "crashed":
            raise helper.BrowserFetchError("Camoufox navigation failed (OSError)")
        return outcomes[backend]

    page, calls, _logs = _http_challenged_lookup(monkeypatch, outcome)
    assert calls == expected_calls
    assert page == (None if paused else "Rendered")
    assert session.automatic_check_paused() is paused


def test_camoufox_that_met_the_check_and_ran_out_of_time_does_not_hand_over_to_chrome(monkeypatch):
    from common import common_romanceio_camoufox as module
    from common import common_romanceio_fetch_helper as helper
    from common import common_romanceio_session as session
    from common import common_romanceio_transport as transport

    monkeypatch.setattr(module, "camoufox_available", lambda: True)
    budget = transport.Budget()
    budget.http_challenged = True
    monkeypatch.setattr(transport._state, "budget", budget, raising=False)
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)
    calls: List[str] = []
    logs: List[str] = []

    def fetch(request, log, _abort):
        calls.append(request["backend"])
        log(session.CHALLENGE_SEEN)
        raise helper.BrowserFetchError("Browser exceeded its 119s total time limit (including startup/navigation/quit)")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    with pytest.raises(helper.BrowserFetchError):
        helper.fetch_page("https://www.romance.io/books/test", "romanceio", log_func=logs.append)
    assert calls == ["camoufox"]
    assert any(message.startswith("Skipping chrome:") for message in logs)
    assert session.VERIFY_HINT in logs


def test_calibre_stopping_a_slow_lookup_does_not_pause_automatic_handling(monkeypatch):
    import threading
    from common import common_romanceio_camoufox as module
    from common import common_romanceio_fetch_helper as helper
    from common import common_romanceio_session as session
    from common import common_romanceio_transport as transport

    monkeypatch.setattr(module, "camoufox_available", lambda: True)
    stop = threading.Event()
    budget = transport.Budget(stop)
    budget.http_challenged = True
    monkeypatch.setattr(transport._state, "budget", budget, raising=False)
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(_request, log, _abort):
        log(session.CHALLENGE_SEEN)
        # Calibre gives up on a source once others have answered.
        stop.set()
        raise helper.BrowserFetchError("Browser cancelled; stopping its worker and browser processes")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    with pytest.raises(helper.BrowserFetchError):
        helper.fetch_page("https://www.romance.io/books/test", "romanceio", log_func=print)
    assert not session.automatic_check_paused()


@pytest.mark.parametrize(
    "plugin_name,wait,hinted",
    [("romanceio", 30, True), ("romanceio", 90, False), ("romanceio_fields", 30, False)],
)
def test_metadata_source_says_when_calibre_would_stop_it_before_camoufox_finishes(
    monkeypatch, plugin_name, wait, hinted
):
    import sys
    from types import SimpleNamespace
    from common import common_romanceio_camoufox as module
    from common import common_romanceio_fetch_helper as helper
    from common import common_romanceio_transport as transport

    monkeypatch.setitem(
        sys.modules,
        "calibre.ebooks.metadata.sources.prefs",
        SimpleNamespace(msprefs={"wait_after_first_identify_result": wait}),
    )
    monkeypatch.setattr(module, "camoufox_available", lambda: True)
    budget = transport.Budget()
    budget.http_challenged = True
    monkeypatch.setattr(transport._state, "budget", budget, raising=False)
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)
    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", lambda _request, _log, _abort: "Rendered")
    logs: List[str] = []

    for _route in range(2):
        assert helper.fetch_page("https://www.romance.io/books/test", plugin_name, log_func=logs.append) == "Rendered"
    hints = [message for message in logs if "Max. time to wait after first match is found" in message]
    # Once per lookup, and only for the metadata source when its wait is too short.
    assert len(hints) == (1 if hinted else 0)


def test_pause_holds_when_saved_clearance_was_refused_over_http(monkeypatch):
    from common import common_romanceio_session as session

    _save_chrome_clearance()
    session.reject_clearance_for_http("cf_clearance=earned")
    session.note_automatic_check_failed()
    page, calls, logs = _http_challenged_lookup(monkeypatch, lambda _backend: "Rendered")
    assert (page, calls) == (None, [])
    assert session.VERIFY_HINT in logs


@pytest.mark.parametrize(
    "agent,camoufox,expected",
    [
        # The verification window's Chrome can still reuse its clearance.
        ("Mozilla/5.0 Chrome/156.0.0.0 Safari/537.36", True, ["chrome", "camoufox"]),
        # So can calibre's engine, after the verification without Chrome.
        ("Mozilla/5.0 QtWebEngine/6.9.0 Chrome/130.0 Safari/537.36", False, ["embedded", "chrome"]),
        ("Mozilla/5.0 Firefox/158.0", True, ["camoufox"]),
    ],
)
def test_browser_that_earned_the_clearance_is_tried_first(monkeypatch, agent, camoufox, expected):
    from common import common_romanceio_camoufox as module
    from common import common_romanceio_fetch_helper as helper
    from common import common_romanceio_session as session

    monkeypatch.setattr(module, "camoufox_available", lambda: camoufox)
    cookie = {"name": "cf_clearance", "value": "earned", "domain": ".romance.io", "expiry": time.time() + 3600}
    assert session.save_clearance([cookie], agent)
    session.reject_clearance_for_http("cf_clearance=earned")

    def outcome(backend):
        raise helper.BrowserFetchError(f"{backend} verification challenge did not clear within its navigation budget")

    _page, calls, _logs = _http_challenged_lookup(monkeypatch, outcome)
    assert calls == expected


def test_chrome_reuses_clearance_saved_by_the_same_chrome(chrome_session):
    webengine, session, injected, save = chrome_session
    save("Chrome-UA")
    driver = _FakeChrome(lambda calls: "reload" in calls)

    assert webengine.navigate_chrome(driver, BOOK_REQUEST, lambda _message: None)
    assert injected == ["saved"]
    assert "solve_captcha" not in driver.cdp.calls
    assert session.has_clearance()


def test_chrome_forgets_clearance_that_no_longer_clears_the_check(chrome_session):
    webengine, session, injected, save = chrome_session
    save("Chrome-UA")
    driver = _FakeChrome(lambda _calls: False)

    with pytest.raises(Exception, match="verification challenge"):
        webengine.navigate_chrome(driver, BOOK_REQUEST, lambda _message: None)
    assert injected == ["saved"]
    assert not session.has_clearance()


def test_chrome_ignores_clearance_earned_by_another_browser(chrome_session):
    webengine, session, injected, save = chrome_session
    save("QtWebEngine-UA")
    driver = _FakeChrome(lambda calls: "solve_captcha" in calls)

    assert webengine.navigate_chrome(driver, BOOK_REQUEST, lambda _message: None)
    assert injected == []
    assert session.has_clearance()


def _verification_chrome(monkeypatch, tmp_path, titles):
    """Fake the ordinary Chrome window: DevTools reports each title once, in order."""
    from common import common_romanceio_fetch_helper as helper

    monkeypatch.setenv("CALIBRE_SELENIUM_HOME", str(tmp_path))
    monkeypatch.setattr(helper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(helper, "_find_chrome_binary", lambda: "chrome")
    commands: List[List[str]] = []
    devtools_calls: List[str] = []

    class Process:
        def __init__(self, command, **_kwargs):
            commands.append(command)

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    remaining = list(titles)

    def devtools_json(_port, path):
        if path == "/json/version":
            return {"webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/browser/x", "User-Agent": "Chrome-UA"}
        title = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return [{"type": "page", "url": "https://www.romance.io/", "title": title}]

    def devtools_call(_url, method):
        devtools_calls.append(method)
        cookie = {"name": "cf_clearance", "value": "earned", "domain": ".romance.io", "expires": time.time() + 3600}
        return {"cookies": [cookie]} if remaining[0] != "Just a moment..." else {"cookies": []}

    monkeypatch.setattr(helper.subprocess, "Popen", Process)
    monkeypatch.setattr(helper, "_devtools_json", devtools_json)
    monkeypatch.setattr(helper, "_devtools_call", devtools_call)
    return helper, commands, devtools_calls


def test_verification_chrome_saves_clearance_once_the_user_passes_the_check(monkeypatch, tmp_path):
    from common import common_romanceio_session as session

    helper, commands, devtools_calls = _verification_chrome(
        monkeypatch, tmp_path, ["www.romance.io/", "Just a moment...", "Just a moment...", "Romance.io"]
    )
    logs: List[str] = []
    request = {"url": "https://www.romance.io/", "max_wait": 30}

    assert helper._wait_for_user_in_chrome(request, logs.append) == "Romance.io"
    assert session.browser_clearance("Chrome-UA")["value"] == "earned"
    assert devtools_calls == ["Storage.getCookies", "Browser.close"]
    # An ordinary window: no automation switches and nothing positioned off-screen.
    assert not any("automation" in arg.lower() or "window-position" in arg for arg in commands[0])
    # The same profile returns each time, so Cloudflare sees a browser it has checked before.
    assert f"--user-data-dir={tmp_path / 'romanceio-verify-chrome'}" in commands[0]
    assert session.CHALLENGE_SEEN in logs


def test_verification_chrome_reports_success_before_closing_chrome(monkeypatch, tmp_path):
    helper, _commands, devtools_calls = _verification_chrome(monkeypatch, tmp_path, ["Just a moment...", "Romance.io"])
    handed_over = []

    def ready(page):
        # Closing Chrome can take a while; the dialog need not wait for it.
        assert "Browser.close" not in devtools_calls
        handed_over.append(page)

    assert (
        helper._wait_for_user_in_chrome({"url": "https://www.romance.io/", "max_wait": 30}, print, ready)
        == "Romance.io"
    )
    assert handed_over == ["Romance.io"]
    assert devtools_calls[-1] == "Browser.close"


def test_verification_chrome_explains_a_window_already_using_its_profile(monkeypatch, tmp_path):
    helper, _commands, _calls = _verification_chrome(monkeypatch, tmp_path, ["Romance.io"])

    class HandedOff:
        def __init__(self, _command, **_kwargs):
            pass

        def poll(self):
            return 0

    monkeypatch.setattr(helper.subprocess, "Popen", HandedOff)
    request = {"url": "https://www.romance.io/", "max_wait": 30}
    with pytest.raises(helper.BrowserFetchError, match="earlier verification window is still open"):
        helper._wait_for_user_in_chrome(request, print)


def test_verification_chrome_reports_a_missing_chrome(monkeypatch):
    from common import common_romanceio_fetch_helper as helper

    monkeypatch.setattr(helper, "_find_chrome_binary", lambda: None)
    with pytest.raises(helper.ChromeNotInstalledError, match="Chrome not found"):
        helper._wait_for_user_in_chrome({"url": "https://www.romance.io/"}, print)


def test_devtools_reply_is_reassembled_from_fragments():
    import io
    from common import common_romanceio_fetch_helper as helper

    frames = bytes([0x01, 3]) + b'{"i' + bytes([0x80, 7]) + b'd": 1}'
    assert helper._read_websocket_message(io.BytesIO(frames)) == b'{"id": 1}'


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


@pytest.mark.parametrize("backend", ("embedded", "chrome"))
def test_smoke_accepts_only_expected_challenge_failure(backend):
    from common.run_installed_browser_smoke import _verify_challenge_failure

    if backend == "embedded":
        message = "Embedded web engine timed out waiting for validated content or Cloudflare clearance"
    else:
        message = "Chrome did not return validated content within its navigation budget"
    _verify_challenge_failure(RuntimeError(message), backend, [])


@pytest.mark.parametrize("backend", ("embedded", "chrome"))
@pytest.mark.parametrize("message", ("Browser worker failed", "Embedded web engine renderer exited unexpectedly"))
def test_smoke_rejects_native_crash_as_challenge_failure(backend, message):
    from common.run_installed_browser_smoke import _verify_challenge_failure

    with pytest.raises(AssertionError, match="Challenge lookup failed unexpectedly"):
        _verify_challenge_failure(RuntimeError(message), backend, [])


def test_smoke_rejects_chrome_setup_failure():
    from common.run_installed_browser_smoke import _verify_challenge_failure

    with pytest.raises(AssertionError, match="Challenge lookup failed unexpectedly"):
        _verify_challenge_failure(
            RuntimeError("Browser did not return a page; see the preceding browser log"),
            "chrome",
            ["Chrome error: SessionNotCreatedException: Driver failed to start"],
        )


@pytest.mark.parametrize(
    "message",
    (
        "Chrome did not return validated content within its navigation budget",
        "Chrome verification challenge did not clear within its navigation budget",
    ),
)
def test_smoke_accepts_propagated_chrome_navigation_failure(message):
    from common.run_installed_browser_smoke import _verify_challenge_failure

    _verify_challenge_failure(RuntimeError(message), "chrome", [])


@pytest.mark.parametrize("optimize", (1, 2))
def test_smoke_rejects_worker_crashes_with_optimized_python(optimize):
    import inspect
    from common.run_installed_browser_smoke import _verify_challenge_failure

    namespace: Dict[str, Any] = {}
    code = compile(inspect.getsource(_verify_challenge_failure), "smoke_check", "exec", optimize=optimize)
    exec(code, namespace)  # pylint: disable=exec-used
    with pytest.raises(AssertionError, match="Challenge lookup failed unexpectedly"):
        namespace["_verify_challenge_failure"](RuntimeError("Browser worker failed"), "embedded", [])


@pytest.mark.parametrize(
    "filename",
    (
        "run_installed_browser_smoke.py",
        "run_installed_browser_lifecycle.py",
        "run_installed_live_smoke.py",
        "test_installed_plugins.py",
        "test_release_zip_imports.py",
    ),
)
def test_frozen_calibre_checks_are_not_stripped(filename):
    import ast
    from pathlib import Path

    tree = ast.parse(Path(__file__).with_name(filename).read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.Assert) for node in ast.walk(tree)
    ), f"{filename}: Calibre strips assert statements; use an explicit exception for smoke checks"


@pytest.mark.parametrize(
    "page",
    (
        '<html><body data-peer-connections-blocked="false"></body></html>',
        '<html><body><script>document.body.setAttribute("data-peer-connections-blocked", "true")</script></body></html>',
        '<html><body><div data-peer-connections-blocked="true"></div></body></html>',
    ),
)
def test_smoke_rejects_missing_or_failed_webrtc_check(page):
    from common.run_installed_browser_smoke import _verify_webrtc_blocked

    with pytest.raises(AssertionError, match="did not disable both WebRTC constructors"):
        _verify_webrtc_blocked(page)


def test_smoke_accepts_executed_webrtc_check():
    from common.run_installed_browser_smoke import _verify_webrtc_blocked

    _verify_webrtc_blocked('<html><body data-peer-connections-blocked="true"></body></html>')


@pytest.mark.parametrize("platform_name", ("darwin", "win32", "linux"))
@pytest.mark.parametrize("error_kind", ("access-denied", "errno-zero", "other-os-error"))
def test_smoke_keeps_macos_process_with_unreadable_command_line(monkeypatch, capsys, platform_name, error_kind):
    import psutil
    from common import run_installed_browser_smoke as smoke

    error = {
        "access-denied": psutil.AccessDenied(123),
        "errno-zero": OSError(0, "Undefined error: 0 (originated from sysctl(KERN_PROCARGS2))"),
        "other-os-error": OSError(5, "Input/output error"),
    }[error_kind]

    class Process:
        pid = 123

        def ppid(self):
            return 42

        def cmdline(self):
            raise error

    monkeypatch.setattr(smoke.sys, "platform", platform_name)
    process = Process()
    unreadable: set = set()
    if platform_name == "darwin" and error_kind != "other-os-error":
        for _ in range(2):
            assert not smoke._is_caller_exit_helper(process, 42, unreadable)
        assert unreadable == {process}
        assert capsys.readouterr().out.count("still checking its exit") == 1
    else:
        with pytest.raises(type(error)):
            smoke._is_caller_exit_helper(process, 42, unreadable)
        assert not unreadable


@pytest.mark.parametrize("direct_child,exit_helper", ((True, True), (True, False), (False, True)))
def test_smoke_excludes_only_identified_caller_exit_helper(direct_child, exit_helper):
    from common.run_installed_browser_smoke import _is_caller_exit_helper

    class Process:
        def ppid(self):
            return 42 if direct_child else 99

        def cmdline(self):
            assert direct_child, "Do not inspect command lines of deeper descendants"
            command = "from calibre.utils.safe_atexit import main; main()" if exit_helper else "browser_worker()"
            return ["calibre-debug", "--pipe-worker", command]

    assert _is_caller_exit_helper(Process(), 42, set()) is (direct_child and exit_helper)


def test_smoke_does_not_ignore_macos_parent_inspection_failure(monkeypatch):
    import psutil
    from common import run_installed_browser_smoke as smoke

    class Process:
        def ppid(self):
            raise psutil.AccessDenied(123)

    monkeypatch.setattr(smoke.sys, "platform", "darwin")
    with pytest.raises(psutil.AccessDenied):
        smoke._is_caller_exit_helper(Process(), 42, set())


@pytest.mark.parametrize("failing_attribute", ("name", "cmdline"))
@pytest.mark.parametrize("exit_helper", (False, True))
def test_smoke_monitor_recovers_after_macos_metadata_error(monkeypatch, capsys, failing_attribute, exit_helper):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from common import run_installed_browser_smoke as smoke

    monkeypatch.setattr(smoke.sys, "platform", "darwin")
    error = OSError(0, "Undefined error: 0 (originated from sysctl(KERN_PROCARGS2))")
    command = ["calibre-debug", "--pipe-worker", "from calibre.utils.safe_atexit import main; main()"]
    process = Mock(pid=123)
    process.ppid.return_value = 42
    process.cmdline.return_value = command if exit_helper else ["browser-worker"]
    process.name.return_value = "calibre-debug" if exit_helper else "chrome"
    if failing_attribute == "cmdline":
        process.cmdline.side_effect = [error, process.cmdline.return_value]
    else:
        # A caller-exit helper is not inspected by name once identified.
        process.cmdline.side_effect = [["starting"], process.cmdline.return_value]
        process.name.side_effect = [error, process.name.return_value]
    tracked: set = set()
    violations: set = set()
    unreadable: set = set()
    stopped = Mock()
    stopped.is_set.side_effect = [False, False, True]

    def after_scan(_timeout):
        if stopped.wait.call_count == 1:
            assert process in tracked, "Unreadable processes must still be checked for cleanup"

    stopped.wait.side_effect = after_scan
    smoke._monitor_browser_processes(
        SimpleNamespace(pid=42, children=lambda **_kwargs: [process]),
        stopped,
        tracked,
        violations,
        set(),
        set(),
        unreadable,
        chrome=False,
        check_sockets=False,
    )
    assert stopped.wait.call_count == 2
    assert unreadable == {process}
    assert capsys.readouterr().out.count("still checking its exit") == 1
    assert tracked == (set() if exit_helper else {process})
    # A recovered name must still detect forbidden Chrome launches.
    assert violations == (set() if exit_helper else {"External Chrome process launched"})


@pytest.mark.parametrize("error", (OSError(5, "Input/output error"), RuntimeError("unexpected inspection failure")))
def test_smoke_monitor_reports_unexpected_errors_and_keeps_scanning(error):
    from unittest.mock import Mock
    from common.run_installed_browser_smoke import _monitor_browser_processes

    owner = Mock(pid=42)
    owner.children.side_effect = [error, []]
    stopped = Mock()
    stopped.is_set.side_effect = [False, False, True]
    violations: set = set()
    _monitor_browser_processes(
        owner, stopped, set(), violations, set(), set(), set(), chrome=False, check_sockets=False
    )
    assert owner.children.call_count == 2
    assert violations == {f"Could not inspect browser processes: {type(error).__name__}: {error}"}


@pytest.fixture
def supervised_worker(monkeypatch):
    """Run the caller against a fake supervisor that keeps cleaning up until released."""
    import sys
    import threading
    from types import SimpleNamespace
    from common import common_romanceio_fetch_helper as helper

    process = SimpleNamespace(pid=1, create_time=lambda: 0.0)
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=lambda *_args: process))
    released = threading.Event()
    seen: Dict[str, Any] = {}

    def fork_job(_module, _function, args, heartbeat, no_output):
        assert no_output
        request = seen["request"] = args[0]
        helper._write_browser_log(request, "Navigating")
        response: Dict[str, Any] = {
            "page": "<html>book-stats</html>",
            "logs": [],
            "error_type": None,
            "error_message": None,
        }
        if seen.get("publish", True):
            helper._publish_response(request, response)
        while not released.wait(0.01):
            heartbeat()
        helper._write_browser_log(request, "Browser descendants did not exit; retaining their temporary profile")
        if seen.get("error"):
            raise seen["error"]
        return {"result": response}

    monkeypatch.setitem(sys.modules, "calibre.utils.ipc.simple_worker", SimpleNamespace(fork_job=fork_job))
    return helper, released, seen


def test_lookup_takes_the_browser_answer_without_waiting_for_its_cleanup(supervised_worker):
    helper, released, seen = supervised_worker
    logs: List[str] = []

    page = helper._fetch_page_via_calibre_worker({"backend": "camoufox", "max_wait": 30}, logs.append)
    # Returned while the supervisor is still reaping the browser.
    assert page == "<html>book-stats</html>"
    assert logs == ["Navigating"]
    transport = seen["request"]["transport_dir"]
    assert os.path.isdir(transport)

    released.set()
    deadline = time.monotonic() + 5
    while os.path.exists(transport) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not os.path.exists(transport)
    # What cleanup logs later is marked as belonging to the earlier browser.
    assert logs[-1] == "Earlier browser cleanup: Browser descendants did not exit; retaining their temporary profile"


def test_lookup_waits_for_the_supervisor_when_no_answer_is_published(supervised_worker):
    helper, released, seen = supervised_worker
    seen["publish"] = False
    released.set()
    logs: List[str] = []

    assert helper._fetch_page_via_calibre_worker({"backend": "chrome", "max_wait": 30}, logs.append)
    assert logs == ["Navigating", "Browser descendants did not exit; retaining their temporary profile"]
    assert not os.path.exists(seen["request"]["transport_dir"])

    seen["error"] = RuntimeError("IPC failed")
    with pytest.raises(helper.BrowserFetchError, match="Browser supervisor failed: RuntimeError: IPC failed"):
        helper._fetch_page_via_calibre_worker({"backend": "chrome", "max_wait": 30}, logs.append)


def test_first_published_answer_stands_and_diagnostic_runs_publish_none(tmp_path):
    from common import common_romanceio_fetch_helper as helper

    request = {"transport_dir": str(tmp_path)}
    helper._publish_response(request, {"page": "first"})
    helper._publish_response(request, {"page": "second"})
    assert json.loads((tmp_path / "response.json").read_text(encoding="utf-8")) == {"page": "first"}

    diagnostic = tmp_path / "diagnostic"
    diagnostic.mkdir()
    helper._publish_response({"transport_dir": str(diagnostic), "capture_worker_output": True}, {"page": "x"})
    assert not (diagnostic / "response.json").exists()
