"""
Test that JSON and HTML parsing produce matching metadata results for romanceio plugin.

This test compares the metadata extracted from:
1. JSON API responses
2. Static HTML files (for books in STATIC_TEST_BOOKS)
3. Live HTML pages fetched via SeleniumBase (for all books in test_data.py)

It verifies that romanceio plugin's fields match between parsing strategies:
- romanceio_id
- title
- authors
- tags
- series (+ series_index)
- pubdate

Note: Field-specific tests (star_rating, steam_rating, rating_count) are in
romanceio_fields/test_json_html_parse_matches.py since those fields are only collected
by the romanceio_fields plugin.
"""

import os
import sys
from typing import Any, Dict, List

# Set up module path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.test_data import load_plugin_module, TEST_BOOKS  # type: ignore[import-not-found]  # pylint: disable=import-error
from common.common_romanceio_static_test_data import STATIC_TEST_BOOKS, StaticTestBook  # type: ignore[import-not-found]  # pylint: disable=import-error
from common.common_romanceio_test_utils import (  # type: ignore[import-not-found]  # pylint: disable=import-error
    run_static_file_test,
    run_live_parsing_tests,
    create_json_parser_with_validation,
    create_html_parser_with_validation,
    load_test_json_file,
    load_test_html_file,
    parse_live_test_args,
    select_live_test_books,
)

# Load required modules
parse_json_module = load_plugin_module("romanceio.parse_json", "parse_json.py", plugin_dir)
parse_details_from_json = parse_json_module.parse_details_from_json

parse_html_module = load_plugin_module("romanceio.parse_html", "parse_html.py", plugin_dir)
parse_details_from_html = parse_html_module.parse_details_from_html

tag_mappings_module = load_plugin_module(
    "romanceio.common_romanceio_tag_mappings", "common_romanceio_tag_mappings.py", plugin_dir
)
convert_json_tags_to_display_names = tag_mappings_module.convert_json_tags_to_display_names

# Load common JSON API functions
common_json_api = load_plugin_module(
    "common.common_romanceio_json_api", "common_romanceio_json_api.py", os.path.join(parent_dir, "common")
)
get_book_details_json = common_json_api.get_book_details_json
get_author_details_json = common_json_api.get_author_details_json

# Load common validation functions
common_validation = load_plugin_module(
    "common.common_romanceio_validation", "common_romanceio_validation.py", os.path.join(parent_dir, "common")
)
is_valid_romanceio_id = common_validation.is_valid_romanceio_id

# Fields that romanceio plugin is responsible for
ROMANCEIO_PLUGIN_FIELDS = {"romanceio_id", "title", "authors", "tags", "series", "pubdate", "rating", "description"}


def _parse_json_tag_fields(book_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract tags, rating, and description from raw JSON book dict."""
    info = book_data.get("info", {})
    rating = None
    raw_rating = info.get("avgRating")
    if raw_rating is not None:
        try:
            rating = float(raw_rating)
        except (ValueError, TypeError):
            pass
    return {
        "tags": convert_json_tags_to_display_names(book_data.get("tropes", [])),
        "rating": rating,
        "description": info.get("description") or None,
    }


def _parse_html_extra_fields(root: Any) -> Dict[str, Any]:
    """Extract tags, series, pubdate, rating, and description from HTML root element."""
    series, series_index = parse_html_module.parse_series_from_title(root)
    pubdate = parse_html_module.parse_publish_date(root)
    rating = None
    try:
        rating = parse_html_module.parse_star_rating(root)
    except (ValueError, TypeError, IndexError, AttributeError):
        pass
    return {
        "tags": parse_html_module.parse_tags(root),
        "series": series,
        "series_index": series_index,
        "pubdate": pubdate,
        "rating": rating,
        "description": parse_html_module.parse_description(root),
    }


# Create parsers using common helper functions
parse_json_metadata = create_json_parser_with_validation(
    parse_details_from_json,
    parse_fields_func=_parse_json_tag_fields,
    get_author_details_func=get_author_details_json,
)
parse_html_metadata = create_html_parser_with_validation(
    parse_id_func=parse_html_module.parse_romanceio_id,
    parse_title_func=parse_html_module.parse_title,
    parse_authors_func=parse_html_module.parse_authors,
    parse_fields_func=_parse_html_extra_fields,
)


def _verify_sample_tags(book_data: StaticTestBook) -> None:
    """Assert that known sample tags are present in both JSON and HTML parsed data."""
    if not book_data.sample_tags:
        return

    print(f"  Verifying {len(book_data.sample_tags)} sample tags for {book_data.name}...")

    # JSON path: slugs -> display names
    book_json = load_test_json_file(book_data.json_filename)
    if "books" in book_json and isinstance(book_json.get("books"), list):
        book_json = book_json["books"][0]
    parsed_json = parse_details_from_json(book_json, get_author_details_json)
    json_tags = set(parsed_json.tags or [])
    for tag in book_data.sample_tags:
        assert tag in json_tags, (
            f"Sample tag {tag!r} not found in JSON tags for {book_data.name}. " f"Got: {sorted(json_tags)}"
        )

    # HTML path: display names parsed directly from page
    html_root = load_test_html_file(book_data.html_filename)
    html_tags = set(parse_html_module.parse_tags(html_root))
    for tag in book_data.sample_tags:
        assert tag in html_tags, (
            f"Sample tag {tag!r} not found in HTML tags for {book_data.name}. " f"Got: {sorted(html_tags)}"
        )

    print(f"  ✓ All {len(book_data.sample_tags)} sample tags present in both JSON and HTML")

    # Verify description snippet
    if book_data.description_snippet:
        snippet = book_data.description_snippet
        book_json = load_test_json_file(book_data.json_filename)
        parsed_json = parse_details_from_json(book_json, get_author_details_json)
        assert parsed_json.description and snippet in parsed_json.description, (
            f"Expected JSON description to contain {snippet!r} for {book_data.name}. "
            f"Got: {(parsed_json.description or '')[:200]!r}"
        )
        html_root = load_test_html_file(book_data.html_filename)
        html_desc = parse_html_module.parse_description(html_root)
        assert html_desc and snippet in html_desc, (
            f"Expected HTML description to contain {snippet!r} for {book_data.name}. "
            f"Got: {(html_desc or '')[:200]!r}"
        )
        print("  ✓ description_snippet found in both JSON and HTML")


def test_static_book(book_data: StaticTestBook) -> None:
    """Test a static book's fields across JSON and HTML parsing."""
    run_static_file_test(
        book_name=book_data.name,
        romanceio_id=book_data.romanceio_id,
        json_filename=book_data.json_filename,
        html_filename=book_data.html_filename,
        json_parser=parse_json_metadata,
        html_parser=parse_html_metadata,
        fields_to_compare=ROMANCEIO_PLUGIN_FIELDS,
        plugin_name="romanceio",
    )
    _verify_sample_tags(book_data)


def test_live_parsing(plugin_dir_path: str, test_books: List[Any]) -> None:
    """Test live HTML parsing vs JSON for the given books (romanceio fields only)."""
    # Import fetch_helper for live HTML fetching
    try:
        fetch_helper = load_plugin_module("romanceio.fetch_helper", "fetch_helper.py", plugin_dir_path)
        fetch_romanceio_book_page = fetch_helper.fetch_romanceio_book_page
    except (ImportError, AttributeError, OSError) as e:
        print(f"WARNING: Could not load fetch_helper: {e}")
        print("Skipping live parsing tests.")
        return

    run_live_parsing_tests(
        test_books=test_books,
        json_parser=parse_json_metadata,
        html_parser=parse_html_metadata,
        fields_to_compare=ROMANCEIO_PLUGIN_FIELDS,
        fetch_romanceio_book_page=fetch_romanceio_book_page,
        get_book_details_json=get_book_details_json,
        is_valid_romanceio_id_func=is_valid_romanceio_id,
        plugin_name="romanceio",
    )


def main() -> None:
    run_live, run_all, target_ids = parse_live_test_args()

    print("=" * 80)
    print("ROMANCEIO PLUGIN: JSON vs HTML Parsing Tests")
    print("Testing romanceio plugin fields: romanceio_id, title, authors, tags, series, pubdate, rating, description")
    print("=" * 80)

    # Run static tests (these use saved files)
    for book in STATIC_TEST_BOOKS:
        test_static_book(book)

    books_to_test = select_live_test_books(run_live, run_all, target_ids, TEST_BOOKS)
    if books_to_test is not None:
        test_live_parsing(plugin_dir, books_to_test)

    print("\n" + "=" * 80)
    print("ALL ROMANCEIO TESTS PASSED! ✓")
    print("=" * 80)


if __name__ == "__main__":
    main()
