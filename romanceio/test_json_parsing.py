"""
Test JSON API parsing with static JSON files for romanceio plugin.
This tests the JSON-based approach independently from the HTML scraping approach.
"""

import json
import os
import sys
import types

# Set up module path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.test_data import load_plugin_module
from common.common_romanceio_static_test_data import STATIC_TEST_BOOKS, load_static_json_file
from common.common_romanceio_test_utils import get_first_book_from_test_json

# Set up calibre_plugins namespace for imports
calibre_plugins = types.ModuleType("calibre_plugins")
sys.modules["calibre_plugins"] = calibre_plugins

# Load common modules under calibre_plugins namespace
import common.common_romanceio_validation

sys.modules["calibre_plugins.common"] = types.ModuleType("calibre_plugins.common")
sys.modules["calibre_plugins.common.common_romanceio_validation"] = common.common_romanceio_validation

# Load parse_json module without triggering plugin initialization
parse_json = load_plugin_module("romanceio.parse_json", "parse_json.py", plugin_dir)
parse_book_from_search_json = parse_json.parse_book_from_search_json
parse_details_from_json = parse_json.parse_details_from_json


def load_author_json_from_file(author_id, timeout=30):  # pylint: disable=unused-argument
    """Load author JSON from static test data directory."""
    filename = f"author_{author_id}.json"

    try:
        return load_static_json_file(filename)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def test_json_book(book_data):
    """Test parsing a book from JSON using centralized test data."""
    print("=" * 60)
    print(f"Testing JSON parsing: {book_data.name}")
    print("=" * 60)

    book = get_first_book_from_test_json(
        book_data.search_json_filename, expected_id=book_data.romanceio_id, expected_title=book_data.title
    )

    # Test parse_book_from_search_json with author JSON loading
    romanceio_id, title, authors, cover_url, is_valid, error_reason = parse_book_from_search_json(
        book, load_author_json_from_file
    )

    assert is_valid, f"Parsing failed: {error_reason}"
    print(f"✓ romanceio_id: {romanceio_id}")
    print(f"✓ title: {title}")

    assert cover_url is not None, "Expected cover URL"
    print(f"✓ cover_url: {cover_url}")

    # Authors - extracted from title_series
    print(f"✓ authors: {authors}")

    print(f"\n✓ All {book_data.name} JSON assertions passed\n")


def test_json_details_pubdate(book_data):
    """Test that parse_details_from_json populates pubdate from the detail JSON."""
    print("=" * 60)
    print(f"Testing JSON details pubdate: {book_data.name}")
    print("=" * 60)

    book_json = load_static_json_file(book_data.json_filename)
    parsed = parse_details_from_json(book_json, load_author_json_from_file)

    if book_data.pubdate_year is not None:
        assert parsed.pubdate is not None, f"Expected pubdate to be set (year {book_data.pubdate_year})"
        assert (
            parsed.pubdate.year == book_data.pubdate_year
        ), f"Expected pubdate year {book_data.pubdate_year}, got {parsed.pubdate.year}"
        print(f"✓ pubdate: {parsed.pubdate} (year={parsed.pubdate.year})")
    else:
        print(f"  pubdate: {parsed.pubdate} (no expectation set)")

    print(f"\n✓ {book_data.name} pubdate assertions passed\n")


def test_json_details_series(book_data):
    """Test that parse_details_from_json populates series from the detail JSON."""
    print("=" * 60)
    print(f"Testing JSON details series: {book_data.name}")
    print("=" * 60)

    book_json = load_static_json_file(book_data.json_filename)
    parsed = parse_details_from_json(book_json, load_author_json_from_file)

    if book_data.series_info is not None:
        expected_series_name, expected_series_index = book_data.series_info
        assert parsed.series == expected_series_name, f"Expected series '{expected_series_name}', got '{parsed.series}'"
        assert (
            parsed.series_index == expected_series_index
        ), f"Expected series_index {expected_series_index}, got {parsed.series_index}"
        print(f"✓ series: {parsed.series!r} (index={parsed.series_index})")
    else:
        assert parsed.series is None, f"Expected no series for standalone book, got '{parsed.series}'"
        assert parsed.series_index is None, f"Expected no series_index, got {parsed.series_index}"
        print("✓ series: None (standalone book confirmed)")

    print(f"\n✓ {book_data.name} series assertions passed\n")


def test_json_details_series_inline():
    """Test series parsing with inline JSON representing a book in a series."""
    print("=" * 60)
    print("Testing JSON series parsing (inline data - book in a series)")
    print("=" * 60)

    book_json = {
        "_id": "5455900e87eac3369a913139",
        "info": {
            "title": "Pride, Prejudice, and Cheese Grits",
            "avgRating": 3.6,
            "numRating": 17,
            "published": 1380585600,
        },
        "authors": [{"_id": "5455900e87eac3369a91313a", "name": "Mary Jane Hathaway"}],
        "series": [
            {
                "title": "Jane Austen Takes The South",
                "no": 1,
                "no_display": "1",
                "series": "58fe14f34167a7334263183f",
            }
        ],
        "tropes": [],
        "image": {},
    }

    parsed = parse_details_from_json(book_json)

    assert parsed.series == "Jane Austen Takes The South", f"Expected series name, got '{parsed.series}'"
    assert parsed.series_index == 1.0, f"Expected series_index 1.0, got {parsed.series_index}"
    assert parsed.pubdate is not None, "Expected pubdate to be set"
    assert parsed.pubdate.year == 2013, f"Expected pubdate year 2013, got {parsed.pubdate.year}"

    print(f"✓ series: {parsed.series!r} (index={parsed.series_index})")
    print(f"✓ pubdate year: {parsed.pubdate.year}")
    print("\n✓ Inline series parsing assertions passed\n")


if __name__ == "__main__":
    print("Starting JSON API parsing tests for romanceio plugin...")
    print()

    for static_book in STATIC_TEST_BOOKS:
        test_json_book(static_book)
        test_json_details_pubdate(static_book)
        test_json_details_series(static_book)

    test_json_details_series_inline()

    print("=" * 60)
    print("=" * 60)
    print("All JSON API tests passed!")
    print("=" * 60)
