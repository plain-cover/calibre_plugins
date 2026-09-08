"""
Core JSON API functions for Romance.io.
This module contains only the low-level JSON API calls with no plugin-specific parsing.
Use this to fetch raw JSON data, then parse it in plugin-specific modules.
"""

import json
from typing import Optional, Dict, Any, List, Callable
from urllib.parse import quote
from urllib.request import Request
from urllib.error import HTTPError

from .common_romanceio_transport import HttpRateLimitError, open_request
from .common_romanceio_session import clearance_headers, discard_clearance


class JsonApiEndpointError(RuntimeError):
    """Raised when a Romance.io JSON API endpoint returns HTTP 404 (endpoint is down/retired)."""

    def __init__(self, message: str, url: str = "") -> None:
        super().__init__(message)
        self.url = url


class JsonApiBookNotFoundError(JsonApiEndpointError):
    """Raised when a specific book/author ID returns 404 from the JSON API.

    This is a normal per-item not-found result, NOT an endpoint failure.
    The caller should fall back to HTML scraping but must NOT mark the
    entire endpoint as dead (other books may still be available via JSON).
    """


class JsonApiRateLimitError(HttpRateLimitError):
    """Raised when the Romance.io JSON API returns HTTP 429 Too Many Requests.

    The endpoint is alive but is rate-limiting this client. The caller should
    wait significantly longer before retrying (not just the normal retry_delay).
    """


class JsonApiAccessDeniedError(RuntimeError):
    """Raised when the Romance.io JSON API returns HTTP 403 Forbidden.

    This typically means Cloudflare is blocking plain HTTP requests to the JSON API.
    Search can recover through a supplied browser callback. The orchestrator
    skips identical retries without disabling unrelated endpoints or preventing
    later HTTP requests from using newly obtained clearance.
    """


# Stable URL prefixes for each JSON API endpoint (path up to but not including the resource ID).
# Used by the orchestrator to cache dead endpoints on a per-endpoint basis.
JSON_SEARCH_URL_PREFIX = "https://www.romance.io/json/search_books"
JSON_BOOKS_URL_PREFIX = "https://www.romance.io/json/books"
JSON_AUTHOR_URL_PREFIX = "https://www.romance.io/json/author"


def _make_json_request(url: str, timeout: int = 30, log_func: Optional[Callable] = None) -> Optional[Dict[str, Any]]:
    """
    Make a JSON API request to Romance.io.

    Args:
        url: Full URL to request
        timeout: Request timeout in seconds
        log_func: Optional logging function

    Returns:
        Parsed JSON response dict

    Raises:
        OSError, ValueError, RuntimeError: On connection, timeout, or parsing errors
    """
    if log_func:
        log_func(f"JSON API request: {url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    cached_headers = clearance_headers(url)
    headers.update(cached_headers)
    if cached_headers and log_func:
        log_func("Using cached Cloudflare clearance for direct JSON HTTP request")
    try:
        req = Request(url, headers=headers)
        with open_request(req, timeout) as response:
            data = response.read()

        if log_func:
            log_func(f"JSON API response received: {len(data)} bytes")

        result = json.loads(data.decode("utf-8"))
        return result
    except HTTPError as e:
        if e.code == 404:
            msg = f"JSON API endpoint unavailable (404): {url}"
            if log_func:
                log_func(msg)
            raise JsonApiEndpointError(msg, url=url) from e
        if e.code == 403:
            discard_clearance(cached_headers.get("Cookie", ""))
            if log_func:
                log_func(f"JSON API request failed: HTTPError 403: {e}")
            raise JsonApiAccessDeniedError("HTTP Error 403: Forbidden") from e
        if e.code == 429:
            if log_func:
                log_func(f"JSON API request failed: HTTPError 429: {e}")
            raise JsonApiRateLimitError(
                f"HTTP Error 429: {e}", retry_after=e.headers.get("Retry-After") if e.headers is not None else None
            ) from e
        error_msg = f"JSON API request failed: HTTPError {e.code}: {e}"
        if log_func:
            log_func(error_msg)
        raise
    except Exception as e:
        error_msg = f"JSON API request failed: {type(e).__name__}: {e}"
        if log_func:
            log_func(error_msg)
        raise


def search_books_json(
    title: str,
    authors: Optional[List[str]] = None,
    timeout: int = 30,
    log_func: Optional[Callable] = None,
    browser_fetch_func: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """
    Search for books using JSON, optionally retrying a plain-HTTP 403 through a browser.

    Args:
        title: Book title to search for
        authors: List of author names (optional, but recommended for better results)
        timeout: Request timeout in seconds
        log_func: Optional logging function
        browser_fetch_func: Optional callable accepting the JSON URL and returning
            rendered page HTML from the supervised browser. Used only after a 403.

    Returns:
        List of book dicts from JSON response (empty list if no results)

    Raises:
        RuntimeError: If API returns success=false (technical failure)
        OSError, ValueError: On connection, timeout, or parsing errors
    """
    # Import here to avoid circular dependency
    # Use the same search string construction as HTML search
    from .common_romanceio_search import build_search_string  # pylint: disable=import-outside-toplevel

    search_string = build_search_string(title, authors)
    if not search_string:
        search_string = quote(title.strip().encode("utf-8"))

    url = f"https://www.romance.io/json/search_books?search={search_string}"

    try:
        return _parse_search_response(_make_json_request(url, timeout, log_func), log_func)
    except JsonApiAccessDeniedError:
        if browser_fetch_func is None:
            raise
        if log_func:
            log_func("Direct JSON search unavailable; trying JSON/HTML in Qt, then Chrome if needed.")

    from .common_romanceio_fetch_helper import BrowserFetchError, parse_html_from_selenium

    if log_func:
        log_func(f"Browser JSON search request: {url}")
    assert browser_fetch_func is not None
    page = browser_fetch_func(url)
    try:
        if not page:
            raise ValueError("Browser returned no page")
        # The web engine renders application/json in a <pre>; parse its text rather than
        # the HTML serialization so entities and Unicode are decoded correctly.
        root = parse_html_from_selenium(page)
        blocks = root.xpath("//pre")
        if len(blocks) != 1:
            # A browser can recover via HTML in the same session after its JSON
            # route fails. Preserve the existing matching logic and result shape.
            from .common_romanceio_search import _parse_search_results_with_details

            if not root.xpath('//ul[@id="book-results"]//li[@class="has-background"]'):
                raise ValueError("Browser search returned incomplete results")
            match = _parse_search_results_with_details(root, title, authors, log_func or print)
            if not match:
                return []
            book_id, book_title, book_authors = match
            return [
                {
                    "_id": book_id,
                    "info": {"title": book_title},
                    "authors": [{"name": author} for author in book_authors],
                }
            ]
        response = json.loads(blocks[0].text_content())
        return _parse_search_response(response, log_func)
    except (ValueError, TypeError, RuntimeError) as error:
        if isinstance(error, BrowserFetchError):
            raise
        # Do not repeat an unsuccessful browser request three times. The normal
        # orchestrator can still try the separate HTML search fallback.
        raise BrowserFetchError(f"Browser JSON search failed: {error}") from error


def _parse_search_response(result: Any, log_func: Optional[Callable]) -> List[Dict[str, Any]]:
    """Apply the same response contract to HTTP and browser JSON transports."""
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError("JSON API search returned success=false")
    if isinstance(result, dict) and result.get("success") is True:
        books = result.get("books")
        if isinstance(books, list) and all(isinstance(book, dict) for book in books):
            if log_func:
                log_func(f"JSON API search successful: found {len(books)} books")
            return books
    raise RuntimeError("JSON API search returned unexpected format (missing or invalid books list)")


def get_book_details_json(
    romanceio_id: str, timeout: int = 30, log_func: Optional[Callable] = None
) -> Optional[Dict[str, Any]]:
    """
    Get book details using the JSON API.

    Args:
        romanceio_id: Romance.io book ID (MongoDB ObjectId)
        timeout: Request timeout in seconds
        log_func: Optional logging function

    Returns:
        First book dict from JSON response if found, None if book not found or not in JSON API

    Raises:
        RuntimeError: If API returns success=false or unexpected format (technical failure)
        OSError, ValueError: On connection, timeout, or parsing errors
    """
    url = f"https://www.romance.io/json/books/{romanceio_id}"

    try:
        result = _make_json_request(url, timeout, log_func)
    except JsonApiEndpointError as e:
        # 404 for a specific book means this book isn't in the JSON API.
        # Re-raise as JsonApiBookNotFoundError so the orchestrator knows to fall
        # back to HTML for THIS book without marking the entire endpoint as dead.
        msg = f"JSON API: book {romanceio_id} not available via JSON (404)"
        if log_func:
            log_func(msg)
        raise JsonApiBookNotFoundError(msg, url=e.url) from e

    # Check for API success flag
    if result and result.get("success") is False:
        error_msg = f"JSON API returned success=false for {romanceio_id}"
        if log_func:
            log_func(error_msg)
        raise RuntimeError(error_msg)

    # Check for valid data structure
    if result and result.get("success") is True:
        books = result.get("books", [])
        if books and len(books) > 0:
            if log_func:
                log_func(f"JSON API book details successful for {romanceio_id}")
            return books[0]
        # Empty books array means book not found (legitimate result, not a failure)
        if log_func:
            log_func(f"JSON API returned no books for {romanceio_id}")
        return None

    # Unexpected response format
    error_msg = f"JSON API book details returned unexpected format for {romanceio_id}"
    if log_func:
        log_func(error_msg)
    raise RuntimeError(error_msg)


def get_author_details_json(
    author_id: str, timeout: int = 30, log_func: Optional[Callable] = None
) -> Optional[Dict[str, Any]]:
    """
    Get author details using the JSON API.

    Args:
        author_id: Romance.io author ID (MongoDB ObjectId)
        timeout: Request timeout in seconds
        log_func: Optional logging function

    Returns:
        Response dict with author info and books, or None if author not found

    Raises:
        RuntimeError: If API returns success=false or unexpected format (technical failure)
        OSError, ValueError: On connection, timeout, or parsing errors
    """
    url = f"https://www.romance.io/json/author/{author_id}/popular/0/20"

    try:
        result = _make_json_request(url, timeout, log_func)
    except JsonApiEndpointError as e:
        # 404 for a specific author means this author isn't in the JSON API.
        # Re-raise as JsonApiBookNotFoundError so the orchestrator falls back
        # to HTML without marking the entire endpoint as dead.
        msg = f"JSON API: author {author_id} not available via JSON (404)"
        if log_func:
            log_func(msg)
        raise JsonApiBookNotFoundError(msg, url=e.url) from e

    # Check for API success flag
    if result and result.get("success") is False:
        error_msg = f"JSON API returned success=false for author ID {author_id}"
        if log_func:
            log_func(error_msg)
        raise RuntimeError(error_msg)

    # Check for valid data structure
    if result and result.get("success") is True:
        if log_func:
            log_func(f"JSON API author details successful for {author_id}")
        return result

    # Unexpected response format
    error_msg = f"JSON API author details returned unexpected format for {author_id}"
    if log_func:
        log_func(error_msg)
    raise RuntimeError(error_msg)


def get_book_details_json_only(
    romanceio_id: str, parse_func: Callable, log_func: Callable = print, timeout: int = 30
) -> Optional[Dict[str, Any]]:
    """
    Get book details using JSON API only (no fallback).

    This is a pure JSON function - no HTML fallback logic here.

    Args:
        romanceio_id: Romance.io book ID
        parse_func: Function to parse the book JSON
                    Should have signature: (book_json) -> dict of fields
        log_func: Logging function
        timeout: Request timeout in seconds

    Returns:
        Dict with book fields, or None if not found
    """
    if not romanceio_id:
        log_func("get_book_details_json_only: No romanceio_id provided")
        return None

    log_func(f"get_book_details_json_only: Fetching details for {romanceio_id}")

    book_json = get_book_details_json(romanceio_id, timeout, log_func)

    if not book_json:
        log_func("get_book_details_json_only: Failed to get book details")
        return None

    details = parse_func(book_json)

    return details
