"""
Tests that a JSON API 404 (JsonApiEndpointError) is handled correctly:
  - No retries are attempted (returns immediately after the first failure)
  - The error is caught and converted to a graceful None result, not an exception
"""

import sys
import os

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.common_romanceio_json_api import JsonApiEndpointError
from common.common_romanceio_search_orchestrator import (
    SearchResult,
    _retry_with_delay,
    fetch_details_with_fallback,
    search_with_fallback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raise_404(*_args, **_kwargs):
    raise JsonApiEndpointError("JSON API endpoint unavailable (404): https://example.com")


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
