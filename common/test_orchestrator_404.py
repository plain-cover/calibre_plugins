"""Tests that permanent failures (JsonApiEndpointError, ChromeNotInstalledError,
RosettaNotInstalledError) are handled correctly:
  - No retries are attempted (returns immediately after the first failure)
  - The error is caught and converted to a graceful None result, not an exception
"""

import sys
import os

import pytest

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.common_romanceio_json_api import (
    JsonApiEndpointError,
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


@pytest.fixture(autouse=True)
def clear_dead_endpoints():
    """Reset the module-level dead-endpoints set before and after every test."""
    getattr(_orchestrator_mod, _DEAD_SET).clear()
    yield
    getattr(_orchestrator_mod, _DEAD_SET).clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raise_404(*_args, **_kwargs):
    raise JsonApiEndpointError(
        "JSON API endpoint unavailable (404): https://www.romance.io/json/books/abc123",
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


def test_fetch_details_404_falls_through_to_html():
    """On JSON 404, fetch_details_with_fallback should try HTML scraping."""
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


def test_get_details_404_adds_to_dead_set():
    """get_details_with_fallback must cache a 404 so subsequent calls skip JSON."""

    def json_fetch_404(romanceio_id, _log):
        raise JsonApiEndpointError(
            f"JSON API endpoint unavailable (404): https://www.romance.io/json/books/{romanceio_id}",
            url=f"https://www.romance.io/json/books/{romanceio_id}",
        )

    log_func, _ = _collecting_log()
    get_details_with_fallback(
        romanceio_id="abc123",
        json_fetch_func=json_fetch_404,
        html_fetch_func=_return_none,
        log_func=log_func,
    )

    assert _is_endpoint_dead(JSON_BOOKS_URL_PREFIX), "Books endpoint must be cached as dead after 404"
