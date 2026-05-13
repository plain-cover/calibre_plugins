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


def test_no_match_numeric_result_title():
    """Test that a result book with a purely numeric title doesn't incorrectly match a different search.

    Regression test for the original direction of the 'Thirteen' incorrect match bug:
    When the result title is a pure number-word (e.g. "Thirteen"), result_words_unique=[]
    and all_result_words_in_search was previously (0 == 0) = True, causing any search
    by the same author to appear to match it.

    Uses a minimal synthetic result set containing only "Thirteen" by Kelley Armstrong
    to confirm that searching for "Known to the Victim" by Kelley Armstrong returns None.
    """
    print("=" * 60)
    print("Testing JSON Search Matching: Numeric Result Title No Match Case")
    print("=" * 60)

    # Minimal synthetic result set: one book whose title is a pure number-word
    books = [
        {
            "_id": "54553de28c7d2382e0414467",
            "info": {"title": "Thirteen"},
            "authors": [{"name": "Kelley Armstrong"}],
            "series": [],
        }
    ]

    title = "Known to the Victim"
    authors = ["Kelley Armstrong"]

    best_match_id = find_best_json_match(books, title, authors, lambda *a, **k: None)

    assert (
        best_match_id is None
    ), f"Expected None for search against numeric-titled result (original false-match regression), got {best_match_id}"
    print("\n✓ Correctly returned None when result title is a pure number-word\n")


def test_no_match_word_number_search_title():
    """Test that a word-form number search title doesn't incorrectly match another book by the same author.

    Regression test for the symmetric direction of the 'Thirteen' incorrect match bug:
    When the search title is a pure number-word (e.g. "Seven"), search_words_unique=[]
    and all_search_words_in_result was previously (0 == 0) = True, causing any result
    book by the same author to appear to match.

    Uses the Funny Story / Emily Henry search fixture to confirm that searching for
    "Seven" by Emily Henry (not a real book of hers) correctly returns None.
    """
    print("=" * 60)
    print("Testing JSON Search Matching: Word-Number Search Title No Match Case")
    print("=" * 60)

    # Synthetic result set: non-numeric-titled books by Emily Henry.
    books = [
        {"_id": "abc", "info": {"title": "Funny Story"}, "authors": [{"name": "Emily Henry"}], "series": []},
        {"_id": "def", "info": {"title": "Beach Read"}, "authors": [{"name": "Emily Henry"}], "series": []},
        {
            "_id": "ghi",
            "info": {"title": "People We Meet on Vacation"},
            "authors": [{"name": "Emily Henry"}],
            "series": [],
        },
    ]

    # "Seven" by Emily Henry - purely numeric title, same author; not in the result set
    title = "Seven"
    authors = ["Emily Henry"]

    best_match_id = find_best_json_match(books, title, authors, lambda *a, **k: None)

    assert (
        best_match_id is None
    ), f"Expected None for numeric-title search (symmetric false-match regression), got {best_match_id}"
    print("\n✓ Correctly returned None for numeric-title search by same author\n")


def test_match_word_search_vs_digit_result():
    """Test that searching 'Thirteen' matches a result titled '13'.

    Covers the word→digit direction of digit/word equivalence. The digit→word
    direction ("13" finding "Thirteen") is tested by test_match_digit_search_vs_word_result() below.
    The matcher normalises number-words to digits before comparing, so both
    directions should work even though Romance.io always stores the spelled-out form.
    """
    print("=" * 60)
    print("Testing JSON Search Matching: Word Search vs Digit Result")
    print("=" * 60)

    thirteen_id = "54553de28c7d2382e0414467"
    books_digit = [
        {
            "_id": thirteen_id,
            "info": {"title": "13"},
            "authors": [{"name": "Kelley Armstrong"}],
            "series": [],
        }
    ]

    result = find_best_json_match(books_digit, "Thirteen", ["Kelley Armstrong"], lambda *a, **k: None)
    assert result == thirteen_id, f"Expected {thirteen_id} for 'Thirteen' vs '13', got {result}"

    print("\n✓ Correctly matched spelled-out search title to digit result title\n")


def test_match_digit_search_vs_word_result():
    """Test that searching '13' matches a result titled 'Thirteen'.

    Covers the digit→word direction of digit/word equivalence - the primary real-world
    case where Calibre stores '13' but Romance.io returns 'Thirteen'.
    """
    print("=" * 60)
    print("Testing JSON Search Matching: Digit Search vs Word Result")
    print("=" * 60)

    thirteen_id = "54553de28c7d2382e0414467"
    books_word = [
        {
            "_id": thirteen_id,
            "info": {"title": "Thirteen"},
            "authors": [{"name": "Kelley Armstrong"}],
            "series": [],
        }
    ]

    result = find_best_json_match(books_word, "13", ["Kelley Armstrong"], lambda *a, **k: None)
    assert result == thirteen_id, f"Expected {thirteen_id} for '13' vs 'Thirteen', got {result}"

    print("\n✓ Correctly matched digit search title to spelled-out result title\n")


if __name__ == "__main__":
    plugin_name = os.path.basename(os.getcwd())
    print(f"Starting JSON Search Matching Tests (from {plugin_name})...")
    print()

    # Test all books with search data
    for book_data in STATIC_TEST_BOOKS:
        if book_data.search_json_filename:
            test_search_book(book_data)

    # Test non-matching cases
    test_no_match()
    test_no_match_numeric_result_title()
    test_no_match_word_number_search_title()
    test_match_word_search_vs_digit_result()
    test_match_digit_search_vs_word_result()

    print("=" * 60)
    print("All JSON Search Matching Tests Completed!")
    print("=" * 60)
