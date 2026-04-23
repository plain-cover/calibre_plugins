"""
Core JSON API functions for Romance.io.
This module contains only the low-level JSON API calls with no plugin-specific parsing.
Use this to fetch raw JSON data, then parse it in plugin-specific modules.
"""

import json
from typing import Optional, Dict, Any, List, Callable

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote  # type: ignore[attr-defined,no-redef]

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import Request, urlopen  # type: ignore[import-not-found,no-redef]
    from urllib2 import HTTPError  # type: ignore[import-not-found,no-redef]


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

    try:
        req = Request(url, headers=headers)
        response = urlopen(req, timeout=timeout)
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
    title: str, authors: Optional[List[str]] = None, timeout: int = 30, log_func: Optional[Callable] = None
) -> List[Dict[str, Any]]:
    """
    Search for books using the JSON API.

    Args:
        title: Book title to search for
        authors: List of author names (optional, but recommended for better results)
        timeout: Request timeout in seconds
        log_func: Optional logging function

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

    result = _make_json_request(url, timeout, log_func)

    # Check for API success flag
    if result and result.get("success") is False:
        error_msg = "JSON API search returned success=false"
        if log_func:
            log_func(error_msg)
        raise RuntimeError(error_msg)

    if result and result.get("success") is True and "books" in result:
        books = result["books"]
        if log_func:
            log_func(f"JSON API search successful: found {len(books)} books")
        return books

    # Missing books key or unexpected response format
    error_msg = "JSON API search returned unexpected format (missing books key)"
    if log_func:
        log_func(error_msg)
    raise RuntimeError(error_msg)


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
        msg = f"JSON API: book {romanceio_id} not available via JSON (404), will try HTML"
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
        msg = f"JSON API: author {author_id} not available via JSON (404), will try HTML"
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
