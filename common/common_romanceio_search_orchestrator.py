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

from .common_romanceio_json_api import JsonApiEndpointError  # pylint: disable=import-outside-toplevel
from .common_romanceio_fetch_helper import ChromeNotInstalledError  # pylint: disable=import-outside-toplevel


class SearchResult(NamedTuple):
    """Result of a search operation with retry logic.

    Attributes:
        success: True if search completed without exceptions, False if all retries failed
        result: The search result (e.g., romanceio_id), or None if not found or failed
    """

    success: bool
    result: Optional[Any]


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
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                log_func(f"{method_name} retry attempt {attempt}/{max_retries}...")
                time.sleep(retry_delay)

            result = func()

            # Function completed without exception - return success with result
            # (even if result is None, which means search succeeded but no match found)
            if result:
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
            if isinstance(e, JsonApiEndpointError):
                log_func("  Endpoint is down (404), skipping retries.")
                return SearchResult(success=False, result=None)
            if isinstance(e, ChromeNotInstalledError):
                log_func(
                    "  Chrome is not installed - HTML metadata fallback is unavailable.\n"
                    "  Install Chrome to enable this feature: https://www.google.com/chrome/"
                )
                return SearchResult(success=False, result=None)
            if attempt < max_retries:
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

    if html_fetch.result:
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
