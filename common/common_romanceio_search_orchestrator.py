"""
Search orchestration for Romance.io. JSON is preferred for search; book details prefer
HTML because the legacy JSON book-details route is retained only as a fallback.
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
    JsonApiAccessDeniedError,
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

# Timestamps of the last JSON API request per endpoint. Used to enforce a minimum
# inter-request interval so rapid library scans don't trigger rate limiting.
# Keyed by endpoint prefix (e.g. "https://www.romance.io/json/search_books").
# Separate per endpoint so that a search call doesn't force a delay before a detail call.
_last_json_request_time: Dict[str, float] = {}

# Base delay (seconds) before the first retry after a 429 Too Many Requests response.
_RATE_LIMIT_RETRY_SECS: float = 15.0

# How long (seconds) to gate the NEXT book's JSON call after any 429 was seen.
# Kept separate from the per-book retry delay: Chrome scraping typically takes ~15 s,
# which previously consumed the entire 15 s window, leaving the next book with no wait.
# 60 s gives enough breathing room regardless of how long the HTML fallback took.
_RATE_LIMIT_INTER_BOOK_COOLDOWN_SECS: float = 60.0

# Minimum seconds between any two JSON API requests. Prevents bursting through a large
# library with no inter-request gap, which is the root cause of initial 429 responses.
# Empirically, Romance.io allows ~11 requests per 60-second sliding window.
# 60 / 11 = 5.45 s is the theoretical minimum safe interval.
_MIN_JSON_INTERVAL_SECS: float = 6.0


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


class _BookNotFound:
    """Sentinel returned by fetch functions when a book ID is definitively not found (404).

    Distinct from None (technical failure) so that not-found propagates cleanly through the
    orchestrator without being confused with a network error. Use _is_book_not_found() rather
    than isinstance() directly to guard against Calibre plugin-reload identity mismatches.
    """


def _is_book_not_found(val: Any) -> bool:
    """Return True if val is a _BookNotFound sentinel.

    Uses a type-name fallback alongside isinstance() so that Calibre plugin reloads
    (which create a new class identity) don't cause stale isinstance() checks to silently
    return False.
    """
    return isinstance(val, _BookNotFound) or (
        # Module check: both plugins' modules contain "romanceio", which distinguishes
        # this sentinel from any third-party class also named _BookNotFound.
        # Keep the string "_BookNotFound" in sync with the class name above.
        type(val).__name__ == "_BookNotFound"
        and "romanceio" in getattr(type(val), "__module__", "")
    )


def _throttle_json_call(log_func: Callable, endpoint_key: str, abort: Optional[Any] = None) -> None:
    """Enforce rate-limit back-pressure and minimum inter-request spacing before a JSON call.

    Must be called immediately before every JSON API attempt (once per book, not per retry).
    Updates the per-endpoint timestamp so the next call to the same endpoint is correctly spaced.

    Args:
        log_func: Logging function.
        endpoint_key: The endpoint key (from _endpoint_key()) to throttle independently.
        abort: Optional threading.Event; if set, sleep is interrupted and the call returns early.
    """
    # 429 cooldown takes priority: if we hit a rate limit recently, wait out the full window.
    now = time.time()
    rate_limit_elapsed = now - _last_rate_limit_time
    if rate_limit_elapsed < _RATE_LIMIT_INTER_BOOK_COOLDOWN_SECS:
        wait = _RATE_LIMIT_INTER_BOOK_COOLDOWN_SECS - rate_limit_elapsed
        log_func(f"Rate limit cooldown: waiting {wait:.1f}s before JSON API call...")
        deadline = now + wait  # use same clock sample to avoid small overshoot
        while time.time() < deadline:
            if abort is not None and abort.is_set():
                _last_json_request_time[endpoint_key] = time.time()
                return
            time.sleep(min(0.5, deadline - time.time()))
        _last_json_request_time[endpoint_key] = time.time()
        return

    # Enforce minimum inter-request interval per endpoint to prevent burst-triggering rate limits.
    last_time = _last_json_request_time.get(endpoint_key, 0.0)
    deadline = last_time + _MIN_JSON_INTERVAL_SECS
    while time.time() < deadline:
        if abort is not None and abort.is_set():
            _last_json_request_time[endpoint_key] = time.time()
            return
        time.sleep(min(0.5, deadline - time.time()))

    _last_json_request_time[endpoint_key] = time.time()


def _retry_with_delay(
    func: Callable,
    method_name: str,
    max_retries: int,
    retry_delay: float,
    log_func: Callable,
    abort: Optional[Any] = None,
) -> SearchResult:
    """
    Execute a function with retry logic and fixed delay between attempts.

    Retries only occur when the function raises an exception (technical failure).
    If the function completes without exception, its return value is returned immediately,
    even if None (which indicates successful search with no match found).

    Args:
        func: Function to execute (should return value or None, raise exception on technical failure)
        method_name: Name of the method (for logging)
        max_retries: Maximum number of retry attempts
        retry_delay: Delay in seconds between retries
        log_func: Logging function
        abort: Optional threading.Event; if set, retries are abandoned immediately.

    Returns:
        SearchResult with:
        - success=True, result=value: Function completed successfully
        - success=True, result=None: Function completed successfully but no match found
        - success=False, result=None: All retry attempts raised exceptions (technical failure)
    """
    global _last_rate_limit_time  # pylint: disable=global-statement
    next_attempt_delay = retry_delay
    for attempt in range(1, max_retries + 1):
        if abort is not None and abort.is_set():
            log_func(f"{method_name}: aborting (timeout exceeded)")
            return SearchResult(success=False, result=None)
        try:
            if attempt > 1:
                log_func(f"{method_name} retry attempt {attempt}/{max_retries}...")
                sleep_deadline = time.time() + next_attempt_delay
                while time.time() < sleep_deadline:
                    if abort is not None and abort.is_set():
                        log_func(f"{method_name}: aborting during retry wait (timeout exceeded)")
                        return SearchResult(success=False, result=None)
                    time.sleep(min(0.5, sleep_deadline - time.time()))
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
                elif _is_book_not_found(result):
                    log_func(f"○ {method_name}: book not found (404)")
                else:
                    log_func(f"✓ {method_name} found match: {type(result).__name__}")
                if attempt > 1:
                    if _is_book_not_found(result):
                        log_func(f"  (Not found confirmed on attempt {attempt})")
                    else:
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
                log_func("  Book not found in JSON API (404), skipping retries.")
                return SearchResult(success=False, result=None)
            if isinstance(e, JsonApiAccessDeniedError):
                # 403 Forbidden: Cloudflare is blocking plain HTTP requests to the JSON API.
                # This is a site-wide block - mark ALL JSON endpoints dead for this session
                # so subsequent books skip JSON entirely and go straight to Chrome/HTML.
                log_func(
                    "  JSON API blocked (403 Forbidden) - likely Cloudflare protection.\n"
                    "  Marking all JSON endpoints dead for this session; subsequent books will go straight to Chrome."
                )
                _dead_json_endpoints.add(_endpoint_key(JSON_SEARCH_URL_PREFIX))
                _dead_json_endpoints.add(_endpoint_key(JSON_BOOKS_URL_PREFIX))
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
            # type().__name__ check handles cross-module identity mismatch in plugin reload scenarios.
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
                next_attempt_delay = _RATE_LIMIT_RETRY_SECS
                if attempt < max_retries:
                    log_func(f"  Rate limited (429). Will retry in {_RATE_LIMIT_RETRY_SECS:.0f}s...")
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
    abort: Optional[Any] = None,
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
        abort: Optional threading.Event; if set, search is abandoned immediately.

    Returns:
        romanceio_id (str) or None if not found
    """
    # Try JSON API first with retries
    _search_key = _endpoint_key(JSON_SEARCH_URL_PREFIX)
    if _search_key in _dead_json_endpoints:
        log_func("Skipping JSON API search (endpoint returned 404 earlier this session).")
        json_search = SearchResult(success=False, result=None)
    else:
        _throttle_json_call(log_func, _search_key, abort=abort)
        log_func("Attempting JSON API search first...")
        json_search = _retry_with_delay(
            func=lambda: json_search_func(title, authors, log_func),
            method_name="JSON API search",
            max_retries=max_retries,
            retry_delay=retry_delay,
            log_func=log_func,
            abort=abort,
        )

    if json_search.result is not None and not _is_book_not_found(json_search.result):
        return json_search.result

    # success=True, result=None means the API returned cleanly with no match - skip HTML fallback.
    # success=True, result=_BookNotFound should not occur (sentinels are for detail fetch, not search),
    # but if it did we fall through to HTML rather than silently returning None.
    if json_search.success and json_search.result is None:
        log_func("JSON API search completed successfully but found no match. Skipping HTML fallback.")
        return None

    log_func("JSON API had technical failures. Falling back to Chrome/HTML scraping...")
    if abort is not None and abort.is_set():
        log_func("Aborting before Chrome search (timeout exceeded)")
        return None
    html_search = _retry_with_delay(
        func=lambda: html_search_func(title, authors, log_func),
        method_name="HTML scraping",
        max_retries=max_retries,
        retry_delay=retry_delay,
        log_func=log_func,
        abort=abort,
    )

    if html_search.result is not None and not _is_book_not_found(html_search.result):
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
    lightweight_html_fetch_func: Optional[Callable] = None,
    abort: Optional[Any] = None,
) -> Optional[Any]:
    """
    Fetch book details using lightweight HTML first, then Chrome, with JSON last.

    The JSON book-details route has returned 404 for valid books for months, while
    JSON search remains healthy. Keeping the detail route as a final fallback avoids
    wasting a request for every book without removing it entirely; its independent
    live smoke test will show if the endpoint becomes useful again.

    This is the orchestrator for fetching details of a known book by romanceio_id.

    Args:
        romanceio_id: The Romance.io book ID
        json_fetch_func: Function to fetch using JSON API (should return book data or None).
            This is the final fallback for details.
        html_fetch_func: Function to fetch using HTML via Chrome (should return book data or None)
        log_func: Logging function
        max_retries: Maximum retry attempts per method (default: 3)
        retry_delay: Delay in seconds between retries (default: 2.0)
        lightweight_html_fetch_func: Optional function to fetch via lightweight HTTP GET (no Chrome).
            This is the preferred detail method when provided.
        abort: Optional threading.Event; if set, fetch is abandoned immediately.

    Returns:
        Book data (any format), or _BookNotFound if the book definitively does not exist (404),
        or None if all fetch methods failed without a definitive answer.
    """
    if abort is not None and abort.is_set():
        log_func(f"Aborting detail fetch for {romanceio_id} (timeout exceeded)")
        return None

    if lightweight_html_fetch_func is not None:
        log_func(f"Attempting lightweight HTTP fetch first for {romanceio_id}...")
        lw_fetch = _retry_with_delay(
            func=lambda: lightweight_html_fetch_func(romanceio_id, log_func),
            method_name="Lightweight HTTP fetch",
            max_retries=max_retries,
            retry_delay=retry_delay,
            log_func=log_func,
            abort=abort,
        )
        if _is_book_not_found(lw_fetch.result):
            return lw_fetch.result  # book definitively not found, no point trying Chrome
        if lw_fetch.result is not None:
            return lw_fetch.result
        if lw_fetch.success:
            log_func(f"Lightweight HTTP fetch completed but found no data for {romanceio_id}.")
        else:
            log_func(f"Lightweight HTTP fetch failed. Falling back to Chrome HTML scraping for {romanceio_id}...")
    else:
        log_func(f"No lightweight HTTP fetch configured. Attempting Chrome HTML scraping for {romanceio_id}...")

    if abort is not None and abort.is_set():
        log_func(f"Aborting before Chrome fetch for {romanceio_id} (timeout exceeded)")
        return None

    html_fetch = _retry_with_delay(
        func=lambda: html_fetch_func(romanceio_id, log_func),
        method_name="Chrome HTML scraping",
        max_retries=max_retries,
        retry_delay=retry_delay,
        log_func=log_func,
        abort=abort,
    )

    if html_fetch.result is not None:
        return html_fetch.result

    if html_fetch.success:
        log_func(f"Chrome HTML scraping completed but found no data for {romanceio_id}.")
    else:
        log_func(f"Chrome HTML scraping failed for {romanceio_id}.")

    if abort is not None and abort.is_set():
        log_func(f"Aborting before final JSON fetch for {romanceio_id} (timeout exceeded)")
        return None

    # The /json/books route is retained as a last-resort fallback and monitored
    # independently, but it should not add a known-failing request to every book.
    _books_key = _endpoint_key(JSON_BOOKS_URL_PREFIX)
    if _books_key in _dead_json_endpoints:
        log_func(f"Skipping final JSON API fetch for {romanceio_id} (endpoint failed earlier this session).")
        return None

    _throttle_json_call(log_func, _books_key, abort=abort)
    log_func(f"HTML detail methods unavailable; trying JSON API as a final fallback for {romanceio_id}...")
    json_fetch = _retry_with_delay(
        func=lambda: json_fetch_func(romanceio_id, log_func),
        method_name="JSON API fetch",
        max_retries=max_retries,
        retry_delay=retry_delay,
        log_func=log_func,
        abort=abort,
    )

    if json_fetch.result is not None:
        return json_fetch.result

    if json_fetch.success:
        log_func(f"JSON API returned no data for {romanceio_id}.")
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
        _throttle_json_call(log_func, _books_key, abort=None)  # legacy path, no abort support
        log_func(f"Attempting JSON API for book {romanceio_id}...")
        try:
            details = json_fetch_func(romanceio_id, log_func)
            if details and not _is_book_not_found(details):
                log_func(f"✓ JSON API book details successful for {romanceio_id}")
                return details
        except (OSError, ValueError, RuntimeError) as e:
            log_func(f"JSON API book details failed: {e}")

    log_func(f"Falling back to Chrome/HTML scraping for book {romanceio_id}...")

    try:
        details = html_fetch_func(romanceio_id, log_func)
        if details and not _is_book_not_found(details):
            log_func(f"✓ HTML scraping successful for {romanceio_id}")
            return details
        if _is_book_not_found(details):
            log_func(f"○ HTML scraping: book {romanceio_id} not found (404)")
        else:
            log_func(f"○ HTML scraping completed but no data returned for {romanceio_id}")
        return None
    except (OSError, ValueError, RuntimeError) as e:
        log_func(f"HTML scraping also failed: {e}")
        return None
