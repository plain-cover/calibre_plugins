"""Tests that permanent failures (JsonApiEndpointError, ChromeNotInstalledError,
RosettaNotInstalledError) are handled correctly:
  - No retries are attempted (returns immediately after the first failure)
  - The error is caught and converted to a graceful None result, not an exception
"""

import contextlib
import sys
import os

import pytest

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.common_romanceio_json_api import (
    JsonApiEndpointError,
    JsonApiBookNotFoundError,
    JsonApiRateLimitError,
    JsonApiAccessDeniedError,
    JSON_SEARCH_URL_PREFIX,
    JSON_BOOKS_URL_PREFIX,
)
from common.common_romanceio_fetch_helper import ChromeNotInstalledError, RosettaNotInstalledError
from common.common_romanceio_search_orchestrator import (
    SearchResult,
    _retry_with_delay,
    _endpoint_key,
    fetch_details_with_fallback,
    search_with_fallback,
    get_details_with_fallback,
)
import common.common_romanceio_search_orchestrator as _orchestrator_mod

_DEAD_SET = "_dead_json_endpoints"
_RATE_LIMIT_TIME = "_last_rate_limit_time"
_LAST_JSON_REQUEST_TIME = "_last_json_request_time"
_RATE_LIMIT_BASE_RETRY = "_RATE_LIMIT_RETRY_SECS"
_RATE_LIMIT_INTER_BOOK_COOLDOWN = "_RATE_LIMIT_INTER_BOOK_COOLDOWN_SECS"
_MIN_JSON_INTERVAL = "_MIN_JSON_INTERVAL_SECS"


@pytest.fixture(autouse=True)
def clear_orchestrator_state():
    """Reset all module-level state before and after every test."""
    getattr(_orchestrator_mod, _DEAD_SET).clear()
    setattr(_orchestrator_mod, _RATE_LIMIT_TIME, 0.0)
    setattr(_orchestrator_mod, _LAST_JSON_REQUEST_TIME, 0.0)
    setattr(_orchestrator_mod, _RATE_LIMIT_BASE_RETRY, 15.0)
    setattr(_orchestrator_mod, _RATE_LIMIT_INTER_BOOK_COOLDOWN, 60.0)
    setattr(_orchestrator_mod, _MIN_JSON_INTERVAL, 1.0)
    yield
    getattr(_orchestrator_mod, _DEAD_SET).clear()
    setattr(_orchestrator_mod, _RATE_LIMIT_TIME, 0.0)
    setattr(_orchestrator_mod, _LAST_JSON_REQUEST_TIME, 0.0)
    setattr(_orchestrator_mod, _RATE_LIMIT_BASE_RETRY, 15.0)
    setattr(_orchestrator_mod, _RATE_LIMIT_INTER_BOOK_COOLDOWN, 60.0)
    setattr(_orchestrator_mod, _MIN_JSON_INTERVAL, 1.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raise_404(*_args, **_kwargs):
    raise JsonApiEndpointError(
        "JSON API endpoint unavailable (404): https://www.romance.io/json/books/abc123",
        url="https://www.romance.io/json/books/abc123",
    )


def _raise_book_not_found(*_args, **_kwargs):
    """Simulates get_book_details_json when a specific book isn't in the JSON API."""
    raise JsonApiBookNotFoundError(
        "JSON API: book abc123 not available via JSON (404), will try HTML",
        url="https://www.romance.io/json/books/abc123",
    )


def _raise_chrome_not_installed(*_args, **_kwargs):
    raise ChromeNotInstalledError("Chrome not found! Install it first!")


def _raise_rosetta_not_installed(*_args, **_kwargs):
    raise RosettaNotInstalledError('Your Mac needs Rosetta 2 to use UC Mode. Run: "softwareupdate --install-rosetta"')


def _return_none(*_args, **_kwargs):
    return None


def _collecting_log():
    """Return a (log_func, records) pair for inspecting logged messages."""
    records: list[str] = []
    return records.append, records


# ---------------------------------------------------------------------------
# _retry_with_delay tests
# ---------------------------------------------------------------------------


def test_404_does_not_retry():
    """JsonApiEndpointError must exit after exactly 1 attempt, never retrying."""
    attempts = []

    def func():
        attempts.append(1)
        raise JsonApiEndpointError("404")

    log_func, logs = _collecting_log()
    result = _retry_with_delay(func, "JSON API fetch", max_retries=3, retry_delay=0, log_func=log_func)

    assert len(attempts) == 1, f"Expected 1 attempt, got {len(attempts)}"
    assert result == SearchResult(success=False, result=None)
    assert any("skipping retries" in msg.lower() for msg in logs), "Expected skip-retries log message"
    # Must NOT log retry messages
    assert not any("retry attempt" in msg.lower() for msg in logs), "Should not log retry attempts on 404"


def test_404_returns_failure_not_exception():
    """JsonApiEndpointError must be caught and converted to SearchResult(success=False)."""
    log_func, _ = _collecting_log()
    result = _retry_with_delay(_raise_404, "JSON API fetch", max_retries=3, retry_delay=0, log_func=log_func)

    assert isinstance(result, SearchResult)
    assert result.success is False
    assert result.result is None


def test_transient_error_does_retry():
    """RuntimeError (transient) must be retried up to max_retries times (controls group)."""
    attempts = []

    def func():
        attempts.append(1)
        raise RuntimeError("transient")

    log_func, _ = _collecting_log()
    _retry_with_delay(func, "JSON API fetch", max_retries=3, retry_delay=0, log_func=log_func)

    assert len(attempts) == 3, f"Expected 3 attempts for transient error, got {len(attempts)}"


# ---------------------------------------------------------------------------
# fetch_details_with_fallback tests
# ---------------------------------------------------------------------------


def test_book_not_found_does_not_retry():
    """JsonApiBookNotFoundError must exit after 1 attempt and NOT add to the dead set."""
    attempts = []

    def func():
        attempts.append(1)
        raise JsonApiBookNotFoundError(
            "JSON API: book abc123 not available via JSON (404), will try HTML",
            url="https://www.romance.io/json/books/abc123",
        )

    log_func, logs = _collecting_log()
    result = _retry_with_delay(func, "JSON API fetch", max_retries=3, retry_delay=0, log_func=log_func)

    assert len(attempts) == 1, f"Expected 1 attempt, got {len(attempts)}"
    assert result == SearchResult(success=False, result=None)
    assert not _is_endpoint_dead(JSON_BOOKS_URL_PREFIX), "Books endpoint must NOT be marked dead for a per-book 404"
    assert not any("retry attempt" in msg.lower() for msg in logs)


def test_fetch_details_book_not_found_falls_through_to_html():
    """On JsonApiBookNotFoundError, fetch_details_with_fallback must try HTML without marking endpoint dead."""
    html_called = []

    def html_fetch(romanceio_id, _log_func):
        html_called.append(romanceio_id)
        return "html_result"

    log_func, logs = _collecting_log()
    result = fetch_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=_raise_book_not_found,
        html_fetch_func=html_fetch,
        log_func=log_func,
        max_retries=3,
        retry_delay=0,
    )

    assert result == "html_result"
    assert html_called == ["abc123"], "HTML fallback should have been called exactly once"
    assert any("falling back" in msg.lower() for msg in logs)
    assert not _is_endpoint_dead(JSON_BOOKS_URL_PREFIX), "Books endpoint must NOT be marked dead for a per-book 404"


def test_fetch_details_404_falls_through_to_html():
    """On JSON endpoint 404 (JsonApiEndpointError), fetch_details_with_fallback should try HTML scraping."""
    html_called = []

    def html_fetch(romanceio_id, _log_func):
        html_called.append(romanceio_id)
        return "html_result"

    log_func, logs = _collecting_log()
    result = fetch_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=_raise_404,
        html_fetch_func=html_fetch,
        log_func=log_func,
        max_retries=3,
        retry_delay=0,
    )

    assert result == "html_result"
    assert html_called == ["abc123"], "HTML fallback should have been called exactly once"
    assert any("falling back" in msg.lower() for msg in logs)


def test_fetch_details_404_html_also_fails_returns_none():
    """On JSON 404 + HTML failure, result is None with no unhandled exception."""
    log_func, _ = _collecting_log()
    result = fetch_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=_raise_404,
        html_fetch_func=_return_none,
        log_func=log_func,
        max_retries=3,
        retry_delay=0,
    )

    assert result is None


# ---------------------------------------------------------------------------
# search_with_fallback tests
# ---------------------------------------------------------------------------


def test_search_with_fallback_404_falls_through_to_html():
    """On JSON search 404, search_with_fallback should try HTML scraping."""
    html_called = []

    def html_search(title, _authors, _log_func):
        html_called.append(title)
        return "html_id"

    log_func, _ = _collecting_log()
    result = search_with_fallback(
        title="Test Book",
        authors=["Author"],
        json_search_func=lambda title, authors, log: (_ for _ in ()).throw(JsonApiEndpointError("404")),
        html_search_func=html_search,
        log_func=log_func,
        max_retries=3,
        retry_delay=0,
    )

    assert result == "html_id"
    assert html_called == ["Test Book"]


def test_search_with_fallback_404_no_html_returns_none():
    """On JSON 404 and no HTML match, returns None without raising."""
    log_func, _ = _collecting_log()
    result = search_with_fallback(
        title="Test Book",
        authors=["Author"],
        json_search_func=lambda title, authors, log: (_ for _ in ()).throw(JsonApiEndpointError("404")),
        html_search_func=_return_none,
        log_func=log_func,
        max_retries=3,
        retry_delay=0,
    )

    assert result is None


# ---------------------------------------------------------------------------
# ChromeNotInstalledError tests
# ---------------------------------------------------------------------------


def test_chrome_not_installed_does_not_retry():
    """ChromeNotInstalledError must exit after exactly 1 attempt, never retrying."""
    attempts = []

    def func():
        attempts.append(1)
        raise ChromeNotInstalledError("Chrome not found! Install it first!")

    log_func, logs = _collecting_log()
    result = _retry_with_delay(func, "HTML scraping", max_retries=3, retry_delay=0, log_func=log_func)

    assert len(attempts) == 1, f"Expected 1 attempt, got {len(attempts)}"
    assert result == SearchResult(success=False, result=None)
    assert any("chrome is not installed" in msg.lower() for msg in logs)
    assert not any("retry attempt" in msg.lower() for msg in logs)


def test_chrome_not_installed_fetch_details_returns_none():
    """ChromeNotInstalledError during HTML fetch yields None without retrying."""
    log_func, _ = _collecting_log()
    result = fetch_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=_raise_404,
        html_fetch_func=_raise_chrome_not_installed,
        log_func=log_func,
        max_retries=3,
        retry_delay=0,
    )

    assert result is None


# ---------------------------------------------------------------------------
# RosettaNotInstalledError tests
# ---------------------------------------------------------------------------


def test_rosetta_not_installed_does_not_retry():
    """RosettaNotInstalledError must exit after exactly 1 attempt, never retrying."""
    attempts = []

    def func():
        attempts.append(1)
        raise RosettaNotInstalledError("Your Mac needs Rosetta 2 to use UC Mode.")

    log_func, logs = _collecting_log()
    result = _retry_with_delay(func, "HTML scraping", max_retries=3, retry_delay=0, log_func=log_func)

    assert len(attempts) == 1, f"Expected 1 attempt, got {len(attempts)}"
    assert result == SearchResult(success=False, result=None)
    assert any("rosetta" in msg.lower() for msg in logs)
    assert not any("retry attempt" in msg.lower() for msg in logs)


def test_rosetta_not_installed_fetch_details_returns_none():
    """RosettaNotInstalledError during HTML fetch yields None without retrying."""
    log_func, _ = _collecting_log()
    result = fetch_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=_raise_404,
        html_fetch_func=_raise_rosetta_not_installed,
        log_func=log_func,
        max_retries=3,
        retry_delay=0,
    )

    assert result is None


# ---------------------------------------------------------------------------
# Session-caching: _dead_json_endpoints set (per-endpoint granularity)
# ---------------------------------------------------------------------------


def _mark_endpoint_dead(url_prefix: str) -> None:
    getattr(_orchestrator_mod, _DEAD_SET).add(_endpoint_key(url_prefix))


def _is_endpoint_dead(url_prefix: str) -> bool:
    return _endpoint_key(url_prefix) in getattr(_orchestrator_mod, _DEAD_SET)


def test_404_adds_endpoint_to_dead_set():
    """JsonApiEndpointError must add the correct endpoint prefix key to the dead set."""
    _retry_with_delay(_raise_404, "JSON API fetch", max_retries=3, retry_delay=0, log_func=lambda _: None)
    # URL was https://www.romance.io/json/books/abc123 -> key should be the books prefix
    assert _is_endpoint_dead(JSON_BOOKS_URL_PREFIX), "Books endpoint must be in dead set after 404"
    assert not _is_endpoint_dead(JSON_SEARCH_URL_PREFIX), "Search endpoint must NOT be in dead set"


def test_search_skips_json_when_search_endpoint_dead():
    """search_with_fallback skips JSON when the search endpoint is marked dead."""
    _mark_endpoint_dead(JSON_SEARCH_URL_PREFIX)
    json_called = []

    def json_search(title, _authors, _log):
        json_called.append(title)
        return "json_id"

    log_func, logs = _collecting_log()
    search_with_fallback(
        title="Test Book",
        authors=["Author"],
        json_search_func=json_search,
        html_search_func=_return_none,
        log_func=log_func,
        max_retries=1,
        retry_delay=0,
    )

    assert not json_called, "JSON search must not be called when search endpoint is known-dead"
    assert any("404" in msg.lower() or "skipping" in msg.lower() for msg in logs)


def test_search_not_skipped_when_only_books_endpoint_dead():
    """Marking the books endpoint dead must NOT skip the search endpoint."""
    _mark_endpoint_dead(JSON_BOOKS_URL_PREFIX)
    json_called = []

    def json_search(title, _authors, _log):
        json_called.append(title)
        return "json_id"

    log_func, _ = _collecting_log()
    result = search_with_fallback(
        title="Test Book",
        authors=["Author"],
        json_search_func=json_search,
        html_search_func=_return_none,
        log_func=log_func,
        max_retries=1,
        retry_delay=0,
    )

    assert json_called == ["Test Book"], "JSON search must still be called when only books endpoint is dead"
    assert result == "json_id"


def test_fetch_details_skips_json_when_books_endpoint_dead():
    """fetch_details_with_fallback skips JSON when the books endpoint is marked dead."""
    _mark_endpoint_dead(JSON_BOOKS_URL_PREFIX)
    json_called = []

    def json_fetch(romanceio_id, _log):
        json_called.append(romanceio_id)
        return {"title": "some book"}

    html_called = []

    def html_fetch(romanceio_id, _log):
        html_called.append(romanceio_id)
        return "html_result"

    log_func, _ = _collecting_log()
    result = fetch_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=json_fetch,
        html_fetch_func=html_fetch,
        log_func=log_func,
        max_retries=1,
        retry_delay=0,
    )

    assert not json_called, "JSON fetch must not be called when books endpoint is known-dead"
    assert html_called == ["abc123"], "HTML fallback must still be called"
    assert result == "html_result"


def test_fetch_details_not_skipped_when_only_search_endpoint_dead():
    """Marking the search endpoint dead must NOT skip book detail fetches."""
    _mark_endpoint_dead(JSON_SEARCH_URL_PREFIX)
    json_called = []

    def json_fetch(romanceio_id, _log):
        json_called.append(romanceio_id)
        return {"title": "some book"}

    log_func, _ = _collecting_log()
    fetch_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=json_fetch,
        html_fetch_func=_return_none,
        log_func=log_func,
        max_retries=1,
        retry_delay=0,
    )

    assert json_called == ["abc123"], "JSON fetch must still run when only search endpoint is dead"


def test_get_details_skips_json_when_books_endpoint_dead():
    """get_details_with_fallback skips JSON when the books endpoint is marked dead."""
    _mark_endpoint_dead(JSON_BOOKS_URL_PREFIX)
    json_called = []

    def json_fetch(romanceio_id, _log):
        json_called.append(romanceio_id)
        return {"title": "some book"}

    log_func, _ = _collecting_log()
    get_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=json_fetch,
        html_fetch_func=_return_none,
        log_func=log_func,
    )

    assert not json_called, "JSON fetch must not be called when books endpoint is known-dead"


def test_get_details_book_not_found_falls_through_to_html():
    """When get_book_details_json raises JsonApiBookNotFoundError (per-book 404),
    get_details_with_fallback must fall through to HTML without marking the endpoint dead."""
    html_called = []

    def html_fetch(romanceio_id, _log):
        html_called.append(romanceio_id)
        return "html_result"

    log_func, _ = _collecting_log()
    result = get_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=_raise_book_not_found,
        html_fetch_func=html_fetch,
        log_func=log_func,
    )

    assert html_called == ["abc123"], "HTML fallback must be called when JSON raises book-not-found"
    assert result == "html_result"
    assert not _is_endpoint_dead(JSON_BOOKS_URL_PREFIX), "Books endpoint must NOT be marked dead for a per-book 404"


# ---------------------------------------------------------------------------
# JsonApiRateLimitError (429) tests
# ---------------------------------------------------------------------------

# String constant so the linter cannot resolve it to the protected symbol.
_THROTTLE = "_throttle_json_call"


@contextlib.contextmanager
def _zero_cooldown():
    """Context manager: zero all rate-limit and interval constants so tests don't actually sleep."""
    setattr(_orchestrator_mod, _RATE_LIMIT_BASE_RETRY, 0.0)
    setattr(_orchestrator_mod, _RATE_LIMIT_INTER_BOOK_COOLDOWN, 0.0)
    setattr(_orchestrator_mod, _MIN_JSON_INTERVAL, 0.0)
    try:
        yield
    finally:
        setattr(_orchestrator_mod, _RATE_LIMIT_BASE_RETRY, 15.0)
        setattr(_orchestrator_mod, _RATE_LIMIT_INTER_BOOK_COOLDOWN, 60.0)
        setattr(_orchestrator_mod, _MIN_JSON_INTERVAL, 1.0)


def test_429_does_retry():
    """JsonApiRateLimitError must be retried (unlike 404 which exits immediately)."""
    with _zero_cooldown():
        attempts = []

        def func():
            attempts.append(1)
            raise JsonApiRateLimitError("HTTP Error 429: Too Many Requests")

        log_func, logs = _collecting_log()
        result = _retry_with_delay(func, "JSON API search", max_retries=3, retry_delay=0, log_func=log_func)

        assert len(attempts) == 3, f"Expected 3 attempts for 429, got {len(attempts)}"
        assert result == SearchResult(success=False, result=None)
        assert any("rate limited" in msg.lower() for msg in logs)
        assert any("retry attempt" in msg.lower() for msg in logs)


def test_429_does_not_mark_endpoint_dead():
    """A 429 must NOT add the endpoint to the dead set - the API is alive, just rate-limiting."""
    with _zero_cooldown():

        def func():
            raise JsonApiRateLimitError("HTTP Error 429: Too Many Requests")

        _retry_with_delay(func, "JSON API search", max_retries=3, retry_delay=0, log_func=lambda _: None)

        assert not _is_endpoint_dead(JSON_SEARCH_URL_PREFIX), "Search endpoint must NOT be marked dead after 429"
        assert not _is_endpoint_dead(JSON_BOOKS_URL_PREFIX), "Books endpoint must NOT be marked dead after 429"


def test_429_updates_rate_limit_timestamp():
    """After a 429, _last_rate_limit_time must be updated to a recent timestamp."""
    import time

    with _zero_cooldown():
        before = time.time()

        def func():
            raise JsonApiRateLimitError("HTTP Error 429: Too Many Requests")

        _retry_with_delay(func, "JSON API search", max_retries=1, retry_delay=0, log_func=lambda _: None)

        recorded = getattr(_orchestrator_mod, _RATE_LIMIT_TIME)
        assert recorded >= before, "_last_rate_limit_time must be set to a timestamp after the 429"


def test_429_retry_succeeds_on_second_attempt():
    """If the second attempt after a 429 succeeds, the result is returned correctly."""
    with _zero_cooldown():
        attempts = []

        def func():
            attempts.append(1)
            if len(attempts) == 1:
                raise JsonApiRateLimitError("HTTP Error 429: Too Many Requests")
            return "abc123"

        log_func, logs = _collecting_log()
        result = _retry_with_delay(func, "JSON API search", max_retries=3, retry_delay=0, log_func=log_func)

        assert len(attempts) == 2
        assert result == SearchResult(success=True, result="abc123")
        assert any("succeeded on retry" in msg.lower() for msg in logs)


def test_maybe_wait_no_sleep_without_prior_429():
    """_throttle_json_call must not sleep for 429 cooldown when no prior 429 (min interval also zeroed)."""
    with _zero_cooldown():
        slept: list[float] = []
        original_sleep = _orchestrator_mod.time.sleep

        def mock_sleep(secs: float) -> None:
            slept.append(secs)

        _orchestrator_mod.time.sleep = mock_sleep
        try:
            getattr(_orchestrator_mod, _THROTTLE)(lambda _: None)
            assert not slept, "Should not sleep when no prior 429 and min interval is zeroed"
        finally:
            _orchestrator_mod.time.sleep = original_sleep


def test_maybe_wait_sleeps_after_recent_429():
    """_throttle_json_call must sleep for the 429 cooldown window when a 429 occurred recently."""
    import time

    setattr(_orchestrator_mod, _RATE_LIMIT_TIME, time.time())
    setattr(_orchestrator_mod, _RATE_LIMIT_INTER_BOOK_COOLDOWN, 10.0)
    setattr(_orchestrator_mod, _MIN_JSON_INTERVAL, 0.0)

    slept: list[float] = []
    logged: list[str] = []
    original_sleep = _orchestrator_mod.time.sleep

    def mock_sleep(secs: float) -> None:
        slept.append(secs)

    _orchestrator_mod.time.sleep = mock_sleep
    try:
        getattr(_orchestrator_mod, _THROTTLE)(logged.append)
        assert len(slept) == 1, "Should sleep exactly once"
        assert 9.0 < slept[0] <= 10.0, f"Should sleep close to 10s, got {slept[0]}"
        assert any("cooldown" in msg.lower() for msg in logged)
    finally:
        _orchestrator_mod.time.sleep = original_sleep


def test_throttle_sleeps_for_min_interval():
    """_throttle_json_call must enforce the minimum inter-request interval when no 429 is active."""
    import time

    setattr(_orchestrator_mod, _MIN_JSON_INTERVAL, 5.0)
    setattr(_orchestrator_mod, _LAST_JSON_REQUEST_TIME, time.time())  # just fired a request

    slept: list[float] = []
    logged: list[str] = []
    original_sleep = _orchestrator_mod.time.sleep

    def mock_sleep(secs: float) -> None:
        slept.append(secs)

    _orchestrator_mod.time.sleep = mock_sleep
    try:
        getattr(_orchestrator_mod, _THROTTLE)(logged.append)
        assert len(slept) == 1, "Should sleep once for the minimum interval"
        assert 4.0 < slept[0] <= 5.0, f"Should sleep close to 5s, got {slept[0]}"
        # Minimum interval sleep is silent - no log message expected
        assert not any("cooldown" in msg.lower() for msg in logged)
    finally:
        _orchestrator_mod.time.sleep = original_sleep


# ---------------------------------------------------------------------------
# JsonApiAccessDeniedError (403) tests
# ---------------------------------------------------------------------------


def _raise_403(*_args, **_kwargs):
    raise JsonApiAccessDeniedError("HTTP Error 403: Forbidden")


def test_403_does_not_retry():
    """JsonApiAccessDeniedError must NOT be retried - it's a persistent Cloudflare block."""
    attempts = []

    def func():
        attempts.append(1)
        raise JsonApiAccessDeniedError("HTTP Error 403: Forbidden")

    log_func, _ = _collecting_log()
    result = _retry_with_delay(func, "JSON API search", max_retries=3, retry_delay=0, log_func=log_func)

    assert len(attempts) == 1, f"Expected exactly 1 attempt for 403, got {len(attempts)}"
    assert result == SearchResult(success=False, result=None)


def test_403_marks_all_endpoints_dead():
    """A 403 must mark BOTH search and books endpoints dead for this session."""

    def func():
        raise JsonApiAccessDeniedError("HTTP Error 403: Forbidden")

    _retry_with_delay(func, "JSON API search", max_retries=3, retry_delay=0, log_func=lambda _: None)

    assert _is_endpoint_dead(JSON_SEARCH_URL_PREFIX), "Search endpoint must be marked dead after 403"
    assert _is_endpoint_dead(JSON_BOOKS_URL_PREFIX), "Books endpoint must be marked dead after 403"


def test_403_logs_cloudflare_message():
    """A 403 must log a message mentioning Cloudflare or blocked access."""
    log_func, logs = _collecting_log()

    _retry_with_delay(_raise_403, "JSON API search", max_retries=3, retry_delay=0, log_func=log_func)

    combined = " ".join(logs).lower()
    assert (
        "403" in combined or "blocked" in combined or "cloudflare" in combined
    ), f"Expected a 403/blocked/cloudflare mention in logs, got: {logs}"


def test_403_search_with_fallback_falls_through_to_html():
    """search_with_fallback must fall back to HTML and call html_search when JSON returns 403."""
    html_called = []

    def html_search(title, authors, _log_func):
        html_called.append((title, authors))
        return "abc123"

    log_func, _ = _collecting_log()
    result = search_with_fallback(
        title="Test Book",
        authors=["Test Author"],
        json_search_func=_raise_403,
        html_search_func=html_search,
        log_func=log_func,
        max_retries=1,
        retry_delay=0,
    )

    assert result == "abc123", "HTML fallback result must be returned after 403"
    assert html_called, "HTML search must be called after JSON returns 403"


def test_403_fetch_details_falls_through_to_html():
    """fetch_details_with_fallback must fall through to HTML when JSON returns 403."""
    html_called = []

    def html_fetch(romanceio_id, _log_func):
        html_called.append(romanceio_id)
        return {"title": "some book"}

    log_func, _ = _collecting_log()
    result = fetch_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=_raise_403,
        html_fetch_func=html_fetch,
        log_func=log_func,
        max_retries=1,
        retry_delay=0,
    )

    assert result == {"title": "some book"}, "HTML fallback result must be returned after 403"
    assert html_called == ["abc123"], "HTML fetch must be called after JSON returns 403"


def test_403_subsequent_books_skip_json():
    """After a 403, both search and detail JSON calls must be skipped for all subsequent books."""
    # Simulate: first book triggers 403 during search
    search_count = []
    fetch_count = []

    def json_search(_title, _authors, _log_func):
        search_count.append(1)
        raise JsonApiAccessDeniedError("HTTP Error 403: Forbidden")

    def html_search(_title, _authors, _log_func):
        return "abc123"

    def json_fetch(_romanceio_id, _log_func):
        fetch_count.append(1)
        return {"title": "some book"}

    def html_fetch(_romanceio_id, _log_func):
        return {"title": "some book"}

    log_func, _ = _collecting_log()

    # First book - triggers 403, falls back to HTML
    search_with_fallback("Book 1", ["Author"], json_search, html_search, log_func, max_retries=1, retry_delay=0)

    # After 403, both endpoints are dead, so entire JSON is skipped for subsequent books
    search_with_fallback("Book 2", ["Author"], json_search, html_search, log_func, max_retries=1, retry_delay=0)
    fetch_details_with_fallback("abc456", json_fetch, html_fetch, log_func, max_retries=1, retry_delay=0)

    assert search_count == [1], f"JSON search called {len(search_count)} times, expected exactly 1 (on first book)"
    assert not fetch_count, "JSON fetch must not be called after 403 marked endpoints dead"
