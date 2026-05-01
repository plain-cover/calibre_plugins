"""
Test that JSON and HTML parsing produce matching metadata results for romanceio_fields plugin.

This test compares the field-specific metadata extracted from:
1. JSON API responses
2. Static HTML files (for books in STATIC_TEST_BOOKS)
3. Live HTML pages fetched via SeleniumBase (for all books in test_data.py)

It verifies that romanceio_fields plugin's fields match between parsing strategies:
- star_rating
- steam_rating
- rating_count
- tags (without order-dependent filtering)

Note: The "top N tags" filter won't work because JSON returns tags in a
slightly different order than HTML, so we test all tags instead.

Note: Basic fields (romanceio_id, title, authors) are tested in
romanceio/test_json_html_parse_matches.py since those are collected by the romanceio plugin.
"""

import os
import sys
from typing import Any, List

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
    parse_live_test_args,
    select_live_test_books,
)

# Load romanceio_fields modules
parse_json_fields_module = load_plugin_module("romanceio_fields.parse_json", "parse_json.py", plugin_dir)
parse_fields_from_json = parse_json_fields_module.parse_fields_from_json

parse_html_fields_module = load_plugin_module("romanceio_fields.parse_html", "parse_html.py", plugin_dir)
parse_fields_from_html = parse_html_fields_module.parse_fields_from_html
parse_fields_from_ssr_html = parse_html_fields_module.parse_fields_from_ssr_html

# Load romanceio modules for basic field parsing
romanceio_dir = os.path.join(parent_dir, "romanceio")
parse_json_basic_module = load_plugin_module("romanceio.parse_json", "parse_json.py", romanceio_dir)
parse_details_from_json = parse_json_basic_module.parse_details_from_json

parse_html_basic_module = load_plugin_module("romanceio.parse_html", "parse_html.py", romanceio_dir)

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

# Fields that romanceio_fields plugin is responsible for
ROMANCEIO_FIELDS_PLUGIN_FIELDS = {"star_rating", "steam_rating", "rating_count", "tags"}

# Create parsers using common helper functions
parse_json_metadata = create_json_parser_with_validation(
    parse_details_func=parse_details_from_json,
    parse_fields_func=parse_fields_from_json,
    get_author_details_func=get_author_details_json,
)
parse_html_metadata = create_html_parser_with_validation(
    parse_id_func=parse_html_basic_module.parse_romanceio_id,
    parse_fields_func=parse_fields_from_html,
    max_tags=1000,  # Use large max_tags to get all tags for comparison
)


def test_static_book(book_data: StaticTestBook) -> None:
    """Test a static book with JSON and HTML files."""
    run_static_file_test(
        book_name=book_data.name,
        romanceio_id=book_data.romanceio_id,
        json_filename=book_data.json_filename,
        html_filename=book_data.html_filename,
        json_parser=parse_json_metadata,
        html_parser=parse_html_metadata,
        fields_to_compare=ROMANCEIO_FIELDS_PLUGIN_FIELDS,
        plugin_name="romanceio_fields",
    )


def test_static_book_ssr_vs_json(book_data: StaticTestBook) -> None:
    """Test that SSR parsing produces the same results as JSON API for a static book.

    SSR tags come from the meta description which uses the same slugs as the JSON API
    'tropes' field, so tag sets should be identical. Ratings come from book-stats
    (identical to Chrome). This test enforces that guarantee.
    """
    print("\n" + "=" * 80)
    print(f"TEST: {book_data.name} (SSR vs JSON) - romanceio_fields fields")
    print("=" * 80)

    from common.common_romanceio_static_test_data import load_static_html_file, load_static_json_file  # type: ignore[import-not-found]  # pylint: disable=import-error
    from lxml.html import fromstring

    raw_html = load_static_html_file(book_data.html_filename)
    root = fromstring(raw_html)
    ssr_fields = parse_fields_from_ssr_html(root, max_tags=1000)

    json_data = load_static_json_file(book_data.json_filename)
    json_fields = parse_fields_from_json(json_data)

    errors = []

    # Steam rating: should be identical
    if ssr_fields["steam_rating"] != json_fields["steam_rating"]:
        errors.append(f"  ❌ STEAM MISMATCH: SSR={ssr_fields['steam_rating']}, JSON={json_fields['steam_rating']}")
    else:
        print(f"  ✓ steam_rating: {ssr_fields['steam_rating']}")

    # Star rating: allow tiny float difference
    ssr_star = ssr_fields.get("star_rating")
    json_star = json_fields.get("star_rating")
    if ssr_star is not None and json_star is not None:
        if abs(ssr_star - json_star) > 0.01:
            errors.append(f"  ❌ STAR MISMATCH: SSR={ssr_star}, JSON={json_star}")
        else:
            print(f"  ✓ star_rating: {ssr_star} ≈ {json_star}")
    elif ssr_star != json_star:
        errors.append(f"  ❌ STAR MISMATCH (one is None): SSR={ssr_star}, JSON={json_star}")

    # Rating count: must be identical
    if ssr_fields["rating_count"] != json_fields["rating_count"]:
        errors.append(f"  ❌ COUNT MISMATCH: SSR={ssr_fields['rating_count']}, JSON={json_fields['rating_count']}")
    else:
        print(f"  ✓ rating_count: {ssr_fields['rating_count']}")

    # Tags: must be identical (same underlying slug source)
    ssr_tag_set = set(ssr_fields["tags"])
    json_tag_set = set(json_fields["tags"])
    missing = json_tag_set - ssr_tag_set
    extra = ssr_tag_set - json_tag_set
    if missing or extra:
        errors.append(
            f"  ❌ TAGS MISMATCH:\n"
            f"     SSR={len(ssr_tag_set)}, JSON={len(json_tag_set)}\n"
            f"     Missing from SSR ({len(missing)}): {sorted(missing)}\n"
            f"     Extra in SSR ({len(extra)}): {sorted(extra)}"
        )
    else:
        print(f"  ✓ tags: {len(ssr_tag_set)} (exact match with JSON API)")

    if errors:
        print(f"\n{'=' * 80}")
        for err in errors:
            print(err)
        raise AssertionError(f"SSR vs JSON mismatch for {book_data.name}:\n" + "\n".join(errors))

    print(f"✓ {book_data.name} SSR vs JSON test passed!")


def test_live_parsing(test_books: List[Any], parent_dir_path: str) -> None:
    """Test live HTML parsing vs JSON for the given books (romanceio_fields fields only)."""
    # Import fetch_helper for live HTML fetching from romanceio plugin
    fetch_romanceio_dir = os.path.join(parent_dir_path, "romanceio")
    try:
        fetch_helper = load_plugin_module("romanceio.fetch_helper", "fetch_helper.py", fetch_romanceio_dir)
        fetch_romanceio_book_page = fetch_helper.fetch_romanceio_book_page
    except (ImportError, AttributeError, OSError) as e:
        print(f"WARNING: Could not load fetch_helper: {e}")
        print("Skipping live parsing tests.")
        return

    run_live_parsing_tests(
        test_books=test_books,
        json_parser=parse_json_metadata,
        html_parser=parse_html_metadata,
        fields_to_compare=ROMANCEIO_FIELDS_PLUGIN_FIELDS,
        fetch_romanceio_book_page=fetch_romanceio_book_page,
        get_book_details_json=get_book_details_json,
        is_valid_romanceio_id_func=is_valid_romanceio_id,
        plugin_name="romanceio_fields",
    )


def main() -> None:
    run_live, run_all, target_ids = parse_live_test_args()

    print("=" * 80)
    print("ROMANCEIO_FIELDS PLUGIN: JSON vs HTML Parsing Tests")
    print("Testing romanceio_fields plugin fields: star_rating, steam_rating, rating_count, tags")
    print("=" * 80)

    # Static tests: JSON vs Chrome HTML
    for book in STATIC_TEST_BOOKS:
        test_static_book(book)

    # Static tests: JSON vs SSR (must match exactly since same underlying source)
    for book in STATIC_TEST_BOOKS:
        test_static_book_ssr_vs_json(book)

    books_to_test = select_live_test_books(run_live, run_all, target_ids, TEST_BOOKS)
    if books_to_test is not None:
        test_live_parsing(books_to_test, parent_dir)

    print("\n" + "=" * 80)
    print("ALL ROMANCEIO_FIELDS TESTS PASSED! ✓")
    print("=" * 80)


if __name__ == "__main__":
    main()
