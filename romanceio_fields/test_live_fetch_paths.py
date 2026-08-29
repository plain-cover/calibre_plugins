"""Small, method-specific live smoke tests for Romance.io fetch paths.

Each invocation exercises exactly one external access method so CI reports do
not confuse a JSON failure with a Cloudflare/Chrome failure. Comprehensive
parsing and matching assertions remain in the deterministic fixture tests.

Examples:
    calibre-debug -e test_live_fetch_paths.py -- json-search
    calibre-debug -e test_live_fetch_paths.py -- json-details
    calibre-debug -e test_live_fetch_paths.py -- ssr-details
    calibre-debug -e test_live_fetch_paths.py -- chrome-search
    calibre-debug -e test_live_fetch_paths.py -- chrome-details
    calibre-debug -e test_live_fetch_paths.py -- default
"""

import argparse
import os
import sys
import types
from typing import Any, Dict, List, Optional

# pylint: disable=wrong-import-position

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

# Load local plugin modules without executing the Calibre plugin entry point.
plugin_package = types.ModuleType("romanceio_fields")
plugin_package.__path__ = [PLUGIN_DIR]
sys.modules["romanceio_fields"] = plugin_package

from romanceio_fields.common_romanceio_fetch_helper import (  # type: ignore[import-not-found]
    fetch_book_page_http,
    parse_html_from_selenium,
)
from romanceio_fields.common_romanceio_json_api import (  # type: ignore[import-not-found]
    JsonApiBookNotFoundError,
    get_book_details_json,
    search_books_json,
)
from romanceio_fields.common_romanceio_search import (  # type: ignore[import-not-found]
    find_best_json_match,
    search_for_romanceio_id,
)
from romanceio_fields.common_romanceio_search_orchestrator import (  # type: ignore[import-not-found]
    fetch_details_with_fallback,
    search_with_fallback,
)
from romanceio_fields.fetch_helper import (  # type: ignore[import-not-found]
    fetch_page,
    fetch_romanceio_book_page,
)
from romanceio_fields.parse_html import (  # type: ignore[import-not-found]
    parse_fields_from_html,
    parse_fields_from_ssr_html,
)
from romanceio_fields.parse_json import parse_fields_from_json  # type: ignore[import-not-found]


TEST_TITLE = "Pride and Prejudice"
TEST_AUTHORS = ["Jane Austen"]
EXPECTED_ROMANCEIO_ID = "5484ecd47a5936fb0405756c"
REQUEST_TIMEOUT_SECONDS = 10


def _log(message: str) -> None:
    print(message, flush=True)


def _assert_fields(fields: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    assert isinstance(fields, dict), f"Expected parsed fields, got {type(fields).__name__}"
    assert fields.get("star_rating") is not None, "Missing star rating"
    assert fields.get("rating_count") is not None, "Missing rating count"
    tags = fields.get("tags")
    assert isinstance(tags, list) and tags, "Missing Romance.io tags"
    return fields


def _print_fields(fields: Dict[str, Any]) -> None:
    print(f"Steam rating: {fields.get('steam_rating')}")
    print(f"Star rating: {fields.get('star_rating')}")
    print(f"Rating count: {fields.get('rating_count')}")
    print(f"Tags: {len(fields.get('tags', []))}")


def _search_json(title: str, authors: Optional[List[str]], log_func: Any) -> Optional[str]:
    books = search_books_json(title, authors, timeout=REQUEST_TIMEOUT_SECONDS, log_func=log_func)
    return find_best_json_match(books, title, authors, log_func)


def _search_chrome(title: str, authors: Optional[List[str]], log_func: Any) -> Optional[str]:
    def fetch_with_log(url: str, **kwargs: Any) -> Optional[str]:
        return fetch_page(url, log_func=log_func, **kwargs)

    return search_for_romanceio_id(title, authors, fetch_with_log, log_func=log_func)


def _fetch_json_fields(romanceio_id: str, log_func: Any) -> Optional[Dict[str, Any]]:
    book_json = get_book_details_json(romanceio_id, timeout=REQUEST_TIMEOUT_SECONDS, log_func=log_func)
    return parse_fields_from_json(book_json) if book_json else None


def _fetch_ssr_fields(romanceio_id: str, log_func: Any) -> Dict[str, Any]:
    raw_html, is_valid = fetch_book_page_http(
        romanceio_id,
        log_func=log_func,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not raw_html or not is_valid:
        raise RuntimeError(f"Server-rendered book page was unavailable for {romanceio_id}")
    return parse_fields_from_ssr_html(parse_html_from_selenium(raw_html), max_tags=50)


def _fetch_chrome_fields(romanceio_id: str, log_func: Any) -> Dict[str, Any]:
    url = f"https://www.romance.io/books/{romanceio_id}"
    raw_html, is_valid = fetch_romanceio_book_page(url, log=log_func)
    if not raw_html or not is_valid:
        raise RuntimeError(f"Chrome book-page fetch was unavailable for {romanceio_id}")
    return parse_fields_from_html(parse_html_from_selenium(raw_html), max_tags=50)


def run_json_search() -> None:
    romanceio_id = _search_json(TEST_TITLE, TEST_AUTHORS, _log)
    assert romanceio_id == EXPECTED_ROMANCEIO_ID, f"Unexpected JSON search result: {romanceio_id!r}"
    print(f"PASS: JSON search resolved {romanceio_id}")


def run_ssr_details() -> None:
    fields = _assert_fields(_fetch_ssr_fields(EXPECTED_ROMANCEIO_ID, _log))
    _print_fields(fields)
    print("PASS: lightweight SSR details returned live metadata")


def run_json_details() -> None:
    try:
        result = _fetch_json_fields(EXPECTED_ROMANCEIO_ID, _log)
    except JsonApiBookNotFoundError as error:
        raise AssertionError(f"JSON details path unavailable: {error}") from None
    fields = _assert_fields(result)
    _print_fields(fields)
    print("PASS: JSON details returned live metadata")


def run_chrome_search() -> None:
    romanceio_id = _search_chrome(TEST_TITLE, TEST_AUTHORS, _log)
    assert romanceio_id == EXPECTED_ROMANCEIO_ID, f"Unexpected Chrome search result: {romanceio_id!r}"
    print(f"PASS: Chrome search resolved {romanceio_id}")


def run_chrome_details() -> None:
    fields = _assert_fields(_fetch_chrome_fields(EXPECTED_ROMANCEIO_ID, _log))
    _print_fields(fields)
    print("PASS: Chrome details returned live metadata")


def run_default() -> None:
    romanceio_id = search_with_fallback(
        TEST_TITLE,
        TEST_AUTHORS,
        _search_json,
        _search_chrome,
        log_func=_log,
        max_retries=1,
        retry_delay=0,
    )
    assert romanceio_id == EXPECTED_ROMANCEIO_ID, f"Unexpected default search result: {romanceio_id!r}"
    fields = fetch_details_with_fallback(
        romanceio_id,
        _fetch_json_fields,
        _fetch_chrome_fields,
        log_func=_log,
        max_retries=1,
        retry_delay=0,
        lightweight_html_fetch_func=_fetch_ssr_fields,
    )
    parsed_fields = _assert_fields(fields)
    _print_fields(parsed_fields)
    print("PASS: default SSR -> Chrome -> JSON fallback returned live metadata")


METHODS = {
    "json-search": run_json_search,
    "json-details": run_json_details,
    "ssr-details": run_ssr_details,
    "chrome-search": run_chrome_search,
    "chrome-details": run_chrome_details,
    "default": run_default,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method", choices=METHODS)
    args = parser.parse_args()
    print("=" * 80)
    print(f"Romance.io live path smoke: {args.method}")
    print("=" * 80)
    METHODS[args.method]()


if __name__ == "__main__":
    main()
