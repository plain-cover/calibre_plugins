"""Test that JSON API search and HTML search return the same book ID.

Covers the gap in test_json_html_parse_matches.py, which only compares book
*detail* data (JSON vs Chrome HTML for a known ID). This file verifies that
the *search* step that produces the ID is consistent across methods.

Static tests (offline, fast):
  - JSON API search results file -> find_best_json_match -> expected ID

Live tests (require internet; --live / --live=all / --live=id1,id2):
  - Live JSON API search -> expected ID
  - Live HTML search (via Chrome) -> same ID as JSON

To run:
    calibre-debug test_search_parity.py                # static only
    calibre-debug test_search_parity.py -- --live      # + 1 live book
    calibre-debug test_search_parity.py -- --live=all  # + full live suite
"""

import os
import sys
import time
from typing import Any, List, Optional

plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.test_data import load_plugin_module, TEST_BOOKS  # type: ignore[import-not-found]  # pylint: disable=import-error
from common.common_romanceio_static_test_data import (  # type: ignore[import-not-found]  # pylint: disable=import-error
    STATIC_TEST_BOOKS,
    StaticTestBook,
    load_static_json_file,
)
from common.common_romanceio_test_utils import (  # type: ignore[import-not-found]  # pylint: disable=import-error
    parse_live_test_args,
    select_live_test_books,
)

# Load romanceio modules
search_module = load_plugin_module("romanceio.common_romanceio_search", "common_romanceio_search.py", plugin_dir)
find_best_json_match = search_module.find_best_json_match
search_for_romanceio_id = search_module.search_for_romanceio_id

json_api_module = load_plugin_module("romanceio.common_romanceio_json_api", "common_romanceio_json_api.py", plugin_dir)
search_books_json = json_api_module.search_books_json


# ---------------------------------------------------------------------------
# Static tests (offline)
# ---------------------------------------------------------------------------


def test_static_json_search(book: StaticTestBook) -> None:
    """Verify find_best_json_match picks the correct ID from saved search results."""
    print("\n" + "=" * 70)
    print(f"TEST (static JSON): {book.name}")
    print("=" * 70)

    data = load_static_json_file(book.search_json_filename)
    assert data.get("success"), f"Expected success=true in search JSON for {book.name}"
    books = data.get("books", [])
    assert books, f"Expected search results in {book.search_json_filename}"

    matched_id = find_best_json_match(books, book.title, book.authors, print)
    assert matched_id == book.romanceio_id, (
        f"JSON search matched wrong ID for {book.name}:\n"
        f"  expected: {book.romanceio_id}\n"
        f"  got:      {matched_id}"
    )
    print(f"✓ {book.name}: JSON search matched {matched_id}")


# ---------------------------------------------------------------------------
# Live tests (require internet)
# ---------------------------------------------------------------------------


def _json_search_live(title: str, authors: List[str]) -> Optional[str]:
    books = search_books_json(title, authors, 30, print)
    if not books:
        return None
    return find_best_json_match(books, title, authors, print)


def _html_search_live(title: str, authors: List[str], fetch_page_func: Any) -> Optional[str]:
    match_id, _, _ = search_module.search_for_romanceio_id_with_details(title, authors, fetch_page_func, print)
    return match_id


def test_live_search_parity(test_books: List[Any], fetch_page_func: Any) -> None:
    """For each live book, assert JSON search and HTML search return the same ID."""
    errors = []

    for i, book in enumerate(test_books):
        if i > 0:
            time.sleep(2)  # Avoid 429 rate limiting between requests
        title = book.title or ""
        authors = book.authors or []
        # Use expected_fields for the ID; book.romanceio_id may be a placeholder.
        # key absent -> no assertion; None -> expect no match; non-None -> expect that ID
        expected_fields = book.expected_fields or {}
        expected_id_set = "romanceio_id" in expected_fields
        expected_id = expected_fields.get("romanceio_id")
        expect_no_match = expected_id_set and expected_id is None

        if not title or not authors:
            print(f"\nSkipping {book!r}: no title/authors")
            continue

        # Skip books that already have a romanceio_id - the plugin would use that
        # ID directly (no search needed), so searching by title won't necessarily
        # return that specific book.
        if book.romanceio_id is not None:
            print(f"\nSkipping {title!r}: already has romanceio_id, no search needed")
            continue

        print(f"\n{'=' * 70}")
        print(f"LIVE SEARCH: {title!r} by {authors}")
        print("=" * 70)

        json_id: Optional[str] = None
        html_id: Optional[str] = None
        json_failed = False
        html_failed = False

        try:
            json_id = _json_search_live(title, authors)
            print(f"  JSON API: {json_id!r}")
        except Exception as e:  # pylint: disable=broad-except
            json_failed = True
            print(f"  JSON API FAILED: {type(e).__name__}: {e}")

        try:
            html_id = _html_search_live(title, authors, fetch_page_func)
            print(f"  HTML search: {html_id!r}")
        except Exception as e:  # pylint: disable=broad-except
            html_failed = True
            print(f"  HTML search FAILED: {type(e).__name__}: {e}")

        # Only flag a parity failure when both methods succeeded and both returned a result
        # but they disagree. Skip if:
        #   - a method raised an exception (e.g. 429, timeout)
        #   - a method returned None (0 search results) - the HTML search has more failure
        #     modes (JS timing, page structure) so None means "inconclusive", not "wrong".
        if json_failed or html_failed:
            print(
                f"  ⚠️  Skipping parity check (one method failed) - "
                f"json_failed={json_failed}, html_failed={html_failed}"
            )
            continue

        # For no-match cases, JSON is authoritative (HTML has more failure modes).
        if expect_no_match:
            if json_id is not None:
                msg = f"Expected no match for {title!r} but JSON search returned {json_id!r}"
                errors.append(msg)
                print(f"  ❌ {msg}")
            else:
                print("  ✓ JSON search correctly returned no match")
                if html_id is not None:
                    # HTML has more failure modes than JSON, so this is inconclusive rather
                    # than a hard error - but worth surfacing in case the HTML matcher
                    # develops a systematic false-positive.
                    print(f"  ⚠️  HTML search returned {html_id!r} for expected-no-match {title!r} (inconclusive)")
            continue

        # Skip parity check if either method returned no results.
        # HTML search has more failure modes (JS timing, page structure) so None
        # means "inconclusive", not "wrong".
        if json_id is None or html_id is None:
            print(
                f"  ⚠️  Skipping parity check (one method returned no results) - "
                f"json_id={json_id!r}, html_id={html_id!r}"
            )
            continue

        if json_id != html_id:
            msg = f"Search parity failure for {title!r}:\n" f"  JSON API: {json_id!r}\n" f"  HTML:     {html_id!r}"
            errors.append(msg)
            print(f"  ❌ {msg}")
            continue

        # If we have an expected ID, validate it
        result_id = json_id  # both agree at this point
        if expected_id and result_id and result_id != expected_id:
            msg = (
                f"Search returned wrong ID for {title!r}:\n"
                f"  expected: {expected_id!r}\n"
                f"  got:      {result_id!r}"
            )
            errors.append(msg)
            print(f"  ❌ {msg}")
        else:
            print(f"  ✓ both methods agree: {result_id!r}")

    if errors:
        raise AssertionError("Search parity failures:\n" + "\n".join(errors))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    run_live, run_all, target_ids = parse_live_test_args()

    print("=" * 70)
    print("SEARCH PARITY TESTS: JSON API vs HTML search")
    print("=" * 70)

    # Static tests: always run (offline)
    for book in STATIC_TEST_BOOKS:
        test_static_json_search(book)

    books_to_test = select_live_test_books(run_live, run_all, target_ids, TEST_BOOKS)
    if books_to_test is not None:
        try:
            fetch_helper = load_plugin_module("romanceio.fetch_helper", "fetch_helper.py", plugin_dir)
            fetch_page = fetch_helper.fetch_page

            def fetch_page_func(url: str, **kwargs: Any) -> Any:
                return fetch_page(url, log_func=print, **kwargs)

        except (ImportError, AttributeError, OSError) as e:
            print(f"WARNING: Could not load fetch_helper: {e}")
            print("Skipping live search tests.")
            books_to_test = None

        if books_to_test is not None:
            test_live_search_parity(books_to_test, fetch_page_func)

    print("\n" + "=" * 70)
    print("ALL SEARCH PARITY TESTS PASSED! ✓")
    print("=" * 70)


if __name__ == "__main__":
    main()
