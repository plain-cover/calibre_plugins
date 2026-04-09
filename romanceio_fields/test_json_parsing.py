"""
Test JSON API parsing with static JSON files.
This tests the JSON-based approach independently from the HTML scraping approach.
"""

import os
import sys

# Set up module path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.test_data import load_plugin_module
from common.common_romanceio_static_test_data import STATIC_TEST_BOOKS
from common.common_romanceio_test_utils import load_test_json_file

# Load parse_json module without triggering plugin initialization
parse_json = load_plugin_module("romanceio_fields.parse_json", "parse_json.py", plugin_dir)
parse_fields_from_json = parse_json.parse_fields_from_json


def test_json_book(book_data):
    """Test parsing a book from JSON using centralized test data."""
    print("=" * 60)
    print(f"Testing JSON parsing: {book_data.name}")
    print("=" * 60)

    book = load_test_json_file(book_data.json_filename)

    romanceio_id = book.get("_id")
    title = book.get("info", {}).get("title", "")

    assert romanceio_id == book_data.romanceio_id, f"Wrong ID: expected {book_data.romanceio_id}, got {romanceio_id}"
    assert title == book_data.title, f"Wrong title: expected {book_data.title}, got {title}"

    print(f"✓ romanceio_id: {romanceio_id}")
    print(f"✓ title: {title}")

    # Parse fields using plugin-specific parser
    fields = parse_fields_from_json(book)

    # Ratings
    assert fields["steam_rating"] is not None, "Expected steam rating"
    print(f"✓ steam_rating: {fields['steam_rating']}")
    if book_data.steam_rating is not None:
        assert (
            fields["steam_rating"] == book_data.steam_rating
        ), f"Expected steam rating {book_data.steam_rating}, got {fields['steam_rating']}"

    assert fields["star_rating"] is not None, "Expected star rating"
    assert isinstance(fields["star_rating"], float), "Star rating should be float"
    print(f"✓ star_rating: {fields['star_rating']}")
    if book_data.star_rating is not None:
        # Allow small tolerance for float comparison
        assert (
            abs(fields["star_rating"] - book_data.star_rating) < 0.5
        ), f"Expected star rating ~{book_data.star_rating}, got {fields['star_rating']}"

    assert fields["rating_count"] is not None, "Expected rating count"
    assert fields["rating_count"] > 0, "Rating count should be positive"
    print(f"✓ rating_count: {fields['rating_count']}")

    # Tags
    assert fields["tags"] is not None, "Expected tags"
    assert isinstance(fields["tags"], list), "Tags should be a list"
    assert len(fields["tags"]) > 0, "Expected at least one tag"
    print(f"✓ tags: {len(fields['tags'])} tags found")
    print(f"  Sample tags: {fields['tags'][:5]}")

    # Verify sample tags are present if provided
    if book_data.sample_tags:
        for expected_tag in book_data.sample_tags:
            assert expected_tag in fields["tags"], f"Expected tag '{expected_tag}' not found in tags"

    print(f"\n✓ All {book_data.name} JSON assertions passed\n")


if __name__ == "__main__":
    print("Starting JSON API parsing tests for romanceio_fields plugin...")
    print()

    for static_book in STATIC_TEST_BOOKS:
        test_json_book(static_book)

    print("=" * 60)
    print("=" * 60)
    print("All JSON API tests passed!")
    print("=" * 60)
