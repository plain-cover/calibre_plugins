"""
Test JSON search matching with static search result JSON files.
This tests the matching logic that finds the best book from search results.

This test file can be run from either plugin directory (romanceio or romanceio_fields).
"""

import os
import sys

# Set up module path - work from either plugin dir or common dir
plugin_dir = os.getcwd()
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.common_romanceio_search import find_best_json_match
from common.common_romanceio_static_test_data import STATIC_TEST_BOOKS, load_static_json_file


def test_search_book(book_data):
    """
    Test matching a book from search results using centralized test data.

    Note: The test data should be generated from a search query that includes
    both title and author to match real-world usage, where the plugin passes
    both to search_books_json(). This helps filter out variations and find
    the original book.
    """
    print("=" * 60)
    print(f"Testing JSON Search Matching: {book_data.name}")
    print("=" * 60)

    data = load_static_json_file(book_data.search_json_filename)

    assert data.get("success"), "Expected success=true in JSON"
    books = data.get("books", [])
    assert len(books) > 0, "Expected search results"

    print(f"Found {len(books)} search results")

    best_match_id = find_best_json_match(books, book_data.title, book_data.authors, print)

    assert best_match_id == book_data.romanceio_id, f"Expected {book_data.romanceio_id}, got {best_match_id}"
    print(f"\n✓ Correctly matched to romanceio_id: {best_match_id}")
    print(f"\n✓ All {book_data.name} search matching assertions passed\n")


def test_no_match():
    """Test that non-matching search returns None."""
    print("=" * 60)
    print("Testing JSON Search Matching: No Match Case")
    print("=" * 60)

    # Find the first book with search data
    book_data = next(book for book in STATIC_TEST_BOOKS if book.search_json_filename)
    assert book_data.search_json_filename is not None
    data = load_static_json_file(book_data.search_json_filename)
    books = data.get("books", [])

    # Search for something completely different
    title = "The Nonexistent Book of Imaginary Tales"
    authors = ["Nobody Famous"]

    best_match_id = find_best_json_match(books, title, authors, print)

    assert best_match_id is None, f"Expected None for non-matching search, got {best_match_id}"
    print("\n✓ Correctly returned None for non-matching book\n")


if __name__ == "__main__":
    plugin_name = os.path.basename(os.getcwd())
    print(f"Starting JSON Search Matching Tests (from {plugin_name})...")
    print()

    # Test all books with search data
    for book_data in STATIC_TEST_BOOKS:
        if book_data.search_json_filename:
            test_search_book(book_data)

    # Test non-matching case
    test_no_match()

    print("=" * 60)
    print("All JSON Search Matching Tests Completed!")
    print("=" * 60)
