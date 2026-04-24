"""
Search orchestrator for Romance.io - tries JSON API first, then falls back to HTML scraping.
This separates concerns: JSON search functions vs HTML search functions vs orchestration.
"""

import sys
import os
import time

# Add parent directory to path to import from common
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from typing import Optional, List, Callable, Any, NamedTuple, Dict

from .common_romanceio_json_api import (  # pylint: disable=import-outside-toplevel
    JsonApiEndpointError,
    JsonApiBookNotFoundError,
    JsonApiRateLimitError,
    JSON_SEARCH_URL_PREFIX,
    JSON_BOOKS_URL_PREFIX,
)
from .common_romanceio_fetch_helper import (
    ChromeNotInstalledError,
    RosettaNotInstalledError,
    SeleniumBaseImportError,
)  # pylint: disable=import-outside-toplevel


# Set of URL prefixes for JSON API endpoints that returned 404 this session.
# Keyed by the stable endpoint prefix (e.g. "https://www.romance.io/json/books")
# so that /json/books/abc123 and /json/books/def456 are treated as the same endpoint.
# This prevents re-trying a known-dead endpoint for every book in a large library run
# while leaving other endpoints (e.g. search) unaffected.
_dead_json_endpoints: set = set()

# Rate limit back-pressure: timestamp of the last 429 response from the JSON API.
# Used to insert a cooldown delay before the next JSON API call when rate-limited.
_last_rate_limit_time: float = 0.0

# How long (seconds) to wait before retrying after a 429 Too Many Requests response.
# Also used as a cooldown gate: if a 429 was seen within this window, delay the next call.
_RATE_LIMIT_COOLDOWN_SECS: float = 15.0


def _endpoint_key(url: str) -> str:
    """Return a stable cache key for a URL's endpoint pattern.

    Extracts the first path segment after /json/ so that:
      https://www.romance.io/json/books/abc123      -> https://www.romance.io/json/books
      https://www.romance.io/json/search_books?q=X -> https://www.romance.io/json/search_books
      https://www.romance.io/json/author/abc123/.. -> https://www.romance.io/json/author
    """
    base = url.split("?")[0]  # drop query string
    marker = "/json/"
    idx = base.find(marker)
    if idx == -1:
        return base  # not a /json/ URL - use whole thing as key
    prefix = base[: idx + len(marker)]
    first_segment = base[idx + len(marker) :].split("/")[0]
    return prefix + first_segment


class SearchResult(NamedTuple):
    """Result of a search operation with retry logic.

    Attributes:
        success: True if search completed without exceptions, False if all retries failed
        result: The search result (e.g., romanceio_id), or None if not found or failed
    """

    success: bool
    result: Optional[Any]


def _maybe_wait_for_rate_limit(log_func: Callable) -> None:
    """Sleep if the JSON API was rate-limited recently, to avoid immediate re-triggering."""
    elapsed = time.time() - _last_rate_limit_time
    if elapsed < _RATE_LIMIT_COOLDOWN_SECS:
        wait = _RATE_LIMIT_COOLDOWN_SECS - elapsed
        log_func(f"Rate limit cooldown: waiting {wait:.1f}s before JSON API call...")
        time.sleep(wait)


def _retry_with_delay(
    func: Callable,
    method_name: str,
    max_retries: int,
    retry_delay: float,
    log_func: Callable,
) -> SearchResult:
    """
    Execute a function with retry logic and constant delay between attempts.

    Retries only occur when the function raises an exception (technical failure).
    If the function completes without exception, its return value is returned immediately,
    even if None (which indicates successful search with no match found).

    Args:
        func: Function to execute (should return value or None, raise exception on technical failure)
        method_name: Name of the method (for logging)
        max_retries: Maximum number of retry attempts
        retry_delay: Delay in seconds between retries
        log_func: Logging function

    Returns:
        SearchResult with:
        - success=True, result=value: Function completed successfully
        - success=True, result=None: Function completed successfully but no match found
        - success=False, result=None: All retry attempts raised exceptions (technical failure)
    """
    global _last_rate_limit_time  # pylint: disable=global-statement
    next_attempt_delay = retry_delay
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                log_func(f"{method_name} retry attempt {attempt}/{max_retries}...")
                time.sleep(next_attempt_delay)
                next_attempt_delay = retry_delay  # reset; may be overridden below on next failure

            result = func()

            # Function completed without exception - return success with result
            # (even if result is None, which means search succeeded but no match found)
            if result is not None:
                # Limit log output for large results
                if isinstance(result, str):
                    log_func(f"✓ {method_name} found match: {result}")
                elif isinstance(result, dict):
                    log_func(f"✓ {method_name} found match (dict with {len(result)} keys)")
                else:
                    log_func(f"✓ {method_name} found match: {type(result).__name__}")
                if attempt > 1:
                    log_func(f"  (Succeeded on retry attempt {attempt})")
            else:
                log_func(f"○ {method_name} completed successfully, but no match found")
                if attempt > 1:
                    log_func(f"  (Completed on retry attempt {attempt})")

            return SearchResult(success=True, result=result)

        except Exception as e:  # pylint: disable=broad-except
            error_type = type(e).__name__
            error_msg = str(e)
            log_func(f"✗ {method_name} attempt {attempt} failed: {error_type}: {error_msg}")
            if isinstance(e, JsonApiBookNotFoundError):
                # Per-book/author 404: this item isn't in the JSON API, try HTML.
                # Do NOT mark the endpoint as dead - other books may be available.
                log_func("  Book not found in JSON API (404), skipping retries. Will try HTML.")
                return SearchResult(success=False, result=None)
            if isinstance(e, JsonApiEndpointError):
                log_func("  Endpoint is down (404), skipping retries.")
                _dead_json_endpoints.add(_endpoint_key(e.url))
                return SearchResult(success=False, result=None)
            if isinstance(e, ChromeNotInstalledError):
                log_func(
                    "  Chrome is not installed - HTML metadata fallback is unavailable.\n"
                    "  Install Chrome to enable this feature: https://www.google.com/chrome/"
                )
                return SearchResult(success=False, result=None)
            if isinstance(e, SeleniumBaseImportError) or type(e).__name__ == "SeleniumBaseImportError":
                log_func(
                    "  Browser automation (SeleniumBase) could not be loaded.\n"
                    "  Try reinstalling the plugin or restarting Calibre."
                )
                return SearchResult(success=False, result=None)
            if isinstance(e, RosettaNotInstalledError):
                log_func(
                    "  Your Mac is missing Rosetta 2, a compatibility layer Apple provides for free.\n"
                    "  To install it:\n"
                    "    1. Open Terminal (press Command+Space, type 'Terminal', press Enter)\n"
                    "    2. Copy and paste this command, then press Enter:\n"
                    "       softwareupdate --install-rosetta\n"
                    "    3. Follow any on-screen prompts, then restart Calibre."
                )
                return SearchResult(success=False, result=None)
            if isinstance(e, JsonApiRateLimitError):
                _last_rate_limit_time = time.time()
                next_attempt_delay = _RATE_LIMIT_COOLDOWN_SECS
                if attempt < max_retries:
                    log_func(f"  Rate limited (429). Will retry in {_RATE_LIMIT_COOLDOWN_SECS}s...")
            elif attempt < max_retries:
                log_func(f"  Will retry in {retry_delay}s...")

    log_func(f"✗ {method_name} failed after {max_retries} attempts")
    return SearchResult(success=False, result=None)


def search_with_fallback(
    title: str,
    authors: Optional[List[str]],
    json_search_func: Callable,
    html_search_func: Callable,
    log_func: Callable = print,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> Optional[str]:
    """
    Search for a book's romanceio_id using JSON API first, with fallback to HTML scraping.

    This is the orchestrator that coordinates JSON and HTML search methods with retry logic.

    Args:
        title: Book title
        authors: List of author names
        json_search_func: Function to search using JSON (should return romanceio_id or None)
        html_search_func: Function to search using HTML (should return romanceio_id or None)
        log_func: Logging function
        max_retries: Maximum retry attempts per method (default: 3)
        retry_delay: Delay in seconds between retries (default: 2.0)

    Returns:
        romanceio_id (str) or None if not found
    """
    # Try JSON API first with retries
    _search_key = _endpoint_key(JSON_SEARCH_URL_PREFIX)
    if _search_key in _dead_json_endpoints:
        log_func("Skipping JSON API search (endpoint returned 404 earlier this session).")
        json_search = SearchResult(success=False, result=None)
    else:
        _maybe_wait_for_rate_limit(log_func)
        log_func("Attempting JSON API search first...")
        json_search = _retry_with_delay(
            func=lambda: json_search_func(title, authors, log_func),
            method_name="JSON API search",
            max_retries=max_retries,
            retry_delay=retry_delay,
            log_func=log_func,
        )

    if json_search.result:
        return json_search.result

    if json_search.success:
        log_func("JSON API search completed successfully but found no match. Skipping HTML fallback.")
        return None

    log_func("JSON API had technical failures. Falling back to Chrome/HTML scraping...")
    html_search = _retry_with_delay(
        func=lambda: html_search_func(title, authors, log_func),
        method_name="HTML scraping",
        max_retries=max_retries,
        retry_delay=retry_delay,
        log_func=log_func,
    )

    if html_search.result:
        return html_search.result

    if html_search.success:
        log_func("HTML scraping completed successfully but found no match.")
    else:
        log_func("✗ All search attempts failed")

    return None


def fetch_details_with_fallback(
    romanceio_id: str,
    json_fetch_func: Callable,
    html_fetch_func: Callable,
    log_func: Callable = print,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> Optional[Any]:
    """
    Fetch book details using JSON API first, with fallback to HTML scraping.

    This is the orchestrator for fetching details of a known book by romanceio_id.

    Args:
        romanceio_id: The Romance.io book ID
        json_fetch_func: Function to fetch using JSON API (should return book data or None)
        html_fetch_func: Function to fetch using HTML (should return book data or None)
        log_func: Logging function
        max_retries: Maximum retry attempts per method (default: 3)
        retry_delay: Delay in seconds between retries (default: 2.0)

    Returns:
        Book data (any format) or None if fetch failed
    """
    _books_key = _endpoint_key(JSON_BOOKS_URL_PREFIX)
    if _books_key in _dead_json_endpoints:
        log_func(f"Skipping JSON API fetch for {romanceio_id} (endpoint returned 404 earlier this session).")
        json_fetch = SearchResult(success=False, result=None)
    else:
        _maybe_wait_for_rate_limit(log_func)
        log_func(f"Attempting JSON API fetch for {romanceio_id}...")
        json_fetch = _retry_with_delay(
            func=lambda: json_fetch_func(romanceio_id, log_func),
            method_name="JSON API fetch",
            max_retries=max_retries,
            retry_delay=retry_delay,
            log_func=log_func,
        )

    if json_fetch.result:
        return json_fetch.result

    if json_fetch.success:
        log_func(f"JSON API returned no data for {romanceio_id}. Skipping HTML fallback.")
        return None

    log_func(f"JSON API had technical failures. Falling back to HTML scraping for {romanceio_id}...")
    html_fetch = _retry_with_delay(
        func=lambda: html_fetch_func(romanceio_id, log_func),
        method_name="HTML scraping",
        max_retries=max_retries,
        retry_delay=retry_delay,
        log_func=log_func,
    )

    if html_fetch.result is not None:
        return html_fetch.result

    if html_fetch.success:
        log_func(f"HTML scraping completed but found no data for {romanceio_id}.")
    else:
        log_func("✗ All fetch attempts failed")

    return None


def get_details_with_fallback(
    romanceio_id: str, json_fetch_func: Callable, html_fetch_func: Callable, log_func: Callable = print
) -> Optional[Dict[str, Any]]:
    """
    Get book details using JSON API first, with fallback to HTML scraping.

    This is a simpler orchestrator without retry logic (for backward compatibility).
    For retry support, use fetch_details_with_fallback() instead.

    Args:
        romanceio_id: Romance.io book ID
        json_fetch_func: Function to fetch using JSON (should return dict or None)
        html_fetch_func: Function to fetch using HTML (should return dict or None)
        log_func: Logging function

    Returns:
        Dict with book fields, or None if not found
    """
    _books_key = _endpoint_key(JSON_BOOKS_URL_PREFIX)
    if _books_key in _dead_json_endpoints:
        log_func(f"Skipping JSON API for book {romanceio_id} (endpoint returned 404 earlier this session).")
    else:
        log_func(f"Attempting JSON API for book {romanceio_id}...")
        try:
            details = json_fetch_func(romanceio_id, log_func)
            if details:
                log_func(f"✓ JSON API book details successful for {romanceio_id}")
                return details
        except (OSError, ValueError, RuntimeError) as e:
            log_func(f"JSON API book details failed: {e}")

    log_func(f"Falling back to Chrome/HTML scraping for book {romanceio_id}...")

    try:
        details = html_fetch_func(romanceio_id, log_func)
        if details:
            log_func(f"✓ HTML scraping successful for {romanceio_id}")
        return details
    except (OSError, ValueError, RuntimeError) as e:
        log_func(f"HTML scraping also failed: {e}")
        return None
