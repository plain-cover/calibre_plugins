"""Test Romance.io page parsing with static HTML files."""

import os
import sys
import types
from typing import Callable, List, Optional
from lxml.html import HtmlElement, fromstring

# Set up module path to enable relative imports in jobs.py
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.test_data import load_plugin_module
from common.common_romanceio_static_test_data import STATIC_TEST_BOOKS, StaticTestBook, load_static_html_file

# Make romanceio_fields a package
romanceio_fields = types.ModuleType("romanceio_fields")
romanceio_fields.__path__ = [plugin_dir]
sys.modules["romanceio_fields"] = romanceio_fields

# Load config and parse_html modules using helper
config_module = load_plugin_module("romanceio_fields.config", "config.py", plugin_dir)
parse_html = load_plugin_module("romanceio_fields.parse_html", "parse_html.py", plugin_dir)

parse_steam_rating = parse_html.parse_steam_rating
parse_star_rating = parse_html.parse_star_rating
parse_rating_count = parse_html.parse_rating_count
parse_romance_tags = parse_html.parse_romance_tags


def load_html_file(filename: str) -> Optional[HtmlElement]:
    """Load and parse an HTML file from static test data,
    returning the root element or None if not found.

    First tries the centralized common/common_romanceio_static_test_data/ directory,
    then falls back to the local test_data/ directory for plugin-specific edge case files.
    """
    try:
        raw_html = load_static_html_file(filename)
        return fromstring(raw_html)
    except FileNotFoundError:
        # Try local test_data directory for plugin-specific edge case files
        test_data_dir = os.path.join(os.path.dirname(__file__), "test_data")
        local_file = os.path.join(test_data_dir, filename)

        if os.path.exists(local_file):
            with open(local_file, "rb") as f:
                raw_html = f.read()
            return fromstring(raw_html)

        print(f"Warning: {filename} not found in centralized or local test data, skipping")
        return None


def run_test(test_name: str, filename: str, test_func: Callable[[HtmlElement], None]) -> None:
    """Run a test with common setup and teardown."""
    root = load_html_file(filename)
    if root is None:
        return

    print("=" * 60)
    print(f"Testing {test_name}")
    print("=" * 60)

    test_func(root)

    print(f"✓ All assertions passed for {test_name}")
    print()


def verify_common_fields(root: HtmlElement, expected_steam: Optional[int]) -> None:
    """Verify steam rating, star rating, and rating count for a book."""
    # Test steam rating
    steam = parse_steam_rating(root)
    assert steam == expected_steam, f"Expected steam rating {expected_steam}, got {steam}"
    print(f"✓ Steam rating: {steam}")

    # Test star rating
    star_rating = parse_star_rating(root)
    assert star_rating is not None, "Expected star rating to be found"
    assert isinstance(star_rating, float), f"Expected float, got {type(star_rating)}"
    print(f"✓ Star rating: {star_rating}")

    # Test rating count
    rating_count = parse_rating_count(root)
    assert rating_count is not None, "Expected rating count to be found"
    assert isinstance(rating_count, int), f"Expected int, got {type(rating_count)}"
    assert rating_count > 0, f"Expected positive rating count, got {rating_count}"
    print(f"✓ Rating count: {rating_count}")


def verify_tags(root: HtmlElement, expected_count: Optional[int], expected_tags: List[str]) -> None:
    """Verify romance tags parsing and check for expected tags."""
    tags = parse_romance_tags(root)

    # If count is less than expected, print actual tags for debugging
    if expected_count is not None and len(tags) < expected_count:
        print(f"WARNING: Expected at least {expected_count} tags, got {len(tags)}")
        print(f"Actual tags: {tags}")
        assert False, f"Tag count incorrect: expected at least {expected_count}, got {len(tags)}"

    # Verify that all expected tags are present
    for expected_tag in expected_tags:
        assert expected_tag in tags, f"Expected tag '{expected_tag}' not found in tags: {tags}"

    print(f"✓ Found {len(tags)} tags with all expected tags present")


def verify_max_tags(root: HtmlElement) -> None:
    """Verify that max_tags limiting works correctly."""
    # Simulate what happens in get_romanceio_fields_for_book
    # where tags are sliced: parse_romance_tags(root)[:max_tags]
    max_10 = parse_romance_tags(root)[:10]
    max_5 = parse_romance_tags(root)[:5]
    max_1 = parse_romance_tags(root)[:1]

    assert len(max_10) == 10, f"Expected 10 tags, got {len(max_10)}"
    assert len(max_5) == 5, f"Expected 5 tags, got {len(max_5)}"
    assert len(max_1) == 1, f"Expected 1 tag, got {len(max_1)}"

    print(f"✓ Max tags limiting: [:10]={len(max_10)}, " f"[:5]={len(max_5)}, [:1]={len(max_1)}")


def test_parse_book(book_data: StaticTestBook) -> None:
    """Test parsing a book using centralized test data."""

    def test_logic(root: HtmlElement) -> None:
        verify_common_fields(root, expected_steam=book_data.steam_rating)
        verify_tags(root, expected_count=book_data.expected_tag_count, expected_tags=book_data.sample_tags)
        verify_max_tags(root)

    run_test(book_data.name, book_data.html_filename, test_logic)


def test_parse_no_ratings() -> None:
    """Test parsing a book with no ratings - should handle gracefully."""

    def test_logic(root: HtmlElement) -> None:
        # Test steam rating - should still work or return None gracefully
        steam = parse_steam_rating(root)
        print(f"✓ Steam rating: {steam} (None is acceptable)")

        # Test star rating - should be None when there are no ratings
        star_rating = parse_star_rating(root)
        assert star_rating is None, f"Expected None for book with no ratings, got {star_rating}"
        print(f"✓ Star rating: {star_rating} (None is acceptable)")

        # Test rating count - should be 0 when there are no ratings
        rating_count = parse_rating_count(root)
        assert rating_count == 0, f"Expected 0 for book with no ratings, got {rating_count}"
        print(f"✓ Rating count: {rating_count}")

        # Tags might still exist even if ratings don't
        tags = parse_romance_tags(root)
        print(f"✓ Found {len(tags)} tags (any count is acceptable)")

    run_test("book with no ratings", "no_ratings_source.html", test_logic)


def test_parse_no_tags() -> None:
    """Test parsing a book with no tags - should handle gracefully."""

    def test_logic(root: HtmlElement) -> None:
        # Test steam rating - might exist even if tags don't
        steam = parse_steam_rating(root)
        print(f"✓ Steam rating: {steam} (any value is acceptable)")

        # Test star rating - might exist even if tags don't
        star_rating = parse_star_rating(root)
        print(f"✓ Star rating: {star_rating} (any value is acceptable)")

        # Test rating count - might exist even if tags don't
        rating_count = parse_rating_count(root)
        print(f"✓ Rating count: {rating_count} (any value is acceptable)")

        # Test tags - should return empty list gracefully
        tags = parse_romance_tags(root)
        assert isinstance(tags, list), f"Expected list, got {type(tags)}"
        assert len(tags) == 0, f"Expected 0 tags for book with no tags, got {len(tags)}"
        print(f"✓ Found {len(tags)} tags (0 as expected)")

    run_test("book with no tags", "no_tags_source.html", test_logic)


if __name__ == "__main__":
    for book in STATIC_TEST_BOOKS:
        test_parse_book(book)

    # Test edge cases
    test_parse_no_ratings()
    test_parse_no_tags()
