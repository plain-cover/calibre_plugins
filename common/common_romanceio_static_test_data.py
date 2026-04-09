"""
Centralized static test data for romanceio and romanceio_fields plugins.

This module provides:
1. StaticTestBook class - container for metadata about static test books
2. STATIC_TEST_BOOKS list - defines all books available for static testing
3. Helper functions to load static test files

All static test data files (JSON and HTML) are stored in the
common_romanceio_static_test_data/ subdirectory.

To add a new static test book:
1. Add book metadata to STATIC_TEST_BOOKS below
2. Add the corresponding JSON and HTML files to common_romanceio_static_test_data/
3. Rebuild both plugins to copy the new files
"""

import json
import os
from typing import Dict, List, Optional


class StaticTestBook:
    """
    Metadata for a static test book.

    Attributes:
        name: Display name for the book (e.g., "Pride and Prejudice")
        romanceio_id: The Romance.io book ID
        title: Full title of the book
        authors: List of author names
        author_ids: Dict mapping author names to their Romance.io IDs
        star_rating: Expected star rating (0-5 scale)
        steam_rating: Expected steam rating (0-5 scale)
        rating_count: Approximate expected rating count
        expected_tag_count: Minimum expected tag count (actual may be higher as users add tags)
        sample_tags: List of sample tags expected to be present

    Properties (auto-generated from romanceio_id):
        json_filename: Name of the JSON file (e.g., "5484ecd47a5936fb0405756c.json")
        html_filename: Name of the HTML source file (e.g., "5484ecd47a5936fb0405756c.html")
        search_json_filename: Search results JSON filename (e.g., "search_5484ecd47a5936fb0405756c.json")
        search_html_filename: Search results HTML filename (e.g., "search_5484ecd47a5936fb0405756c.html")
    """

    def __init__(
        self,
        name: str,
        romanceio_id: str,
        title: str,
        authors: List[str],
        author_ids: Dict[str, str],
        star_rating: Optional[float] = None,
        steam_rating: Optional[int] = None,
        rating_count: Optional[int] = None,
        expected_tag_count: Optional[int] = None,
        sample_tags: Optional[List[str]] = None,
        pubdate_year: Optional[int] = None,
        series_info: Optional[tuple] = None,
    ):
        self.name = name
        self.romanceio_id = romanceio_id
        self.title = title
        self.authors = authors
        self.author_ids = author_ids
        self.star_rating = star_rating
        self.steam_rating = steam_rating
        self.rating_count = rating_count
        self.expected_tag_count = expected_tag_count
        self.sample_tags = sample_tags or []
        self.pubdate_year = pubdate_year
        self.series_info: Optional[tuple] = series_info

    @property
    def json_filename(self) -> str:
        """Generate JSON filename from romanceio_id."""
        return f"{self.romanceio_id}.json"

    @property
    def html_filename(self) -> str:
        """Generate HTML filename from romanceio_id."""
        return f"{self.romanceio_id}.html"

    @property
    def search_json_filename(self) -> str:
        """Generate search JSON filename from romanceio_id."""
        return f"search_{self.romanceio_id}.json"

    @property
    def search_html_filename(self) -> str:
        """Generate search HTML filename from romanceio_id."""
        return f"search_{self.romanceio_id}.html"


# List of all static test books available for testing
STATIC_TEST_BOOKS = [
    StaticTestBook(
        name="Pride and Prejudice",
        romanceio_id="5484ecd47a5936fb0405756c",
        title="Pride and Prejudice",
        authors=["Jane Austen"],
        author_ids={"Jane Austen": "545523418c7d2382c5296f43"},
        star_rating=4.54,
        steam_rating=1,
        rating_count=1479,
        expected_tag_count=36,
        sample_tags=[
            "historical",
            "enemies to lovers",
            "england",
            "third person pov",
        ],
        pubdate_year=1813,
        series_info=None,
    ),
    StaticTestBook(
        name="Funny Story",
        romanceio_id="65b604fa00d361e53f20ecfb",
        title="Funny Story",
        authors=["Emily Henry"],
        author_ids={"Emily Henry": "5e82ee17be0aaecf553e7c2f"},
        star_rating=4.30,
        steam_rating=3,
        rating_count=805,
        expected_tag_count=39,
        sample_tags=[
            "fake relationship",
            "contemporary",
            "michigan",
        ],
        pubdate_year=2024,
        series_info=None,
    ),
]


def get_static_test_data_dir() -> str:
    """
    Get the path to the static test data directory.

    Returns:
        Absolute path to common_romanceio_static_test_data/ directory

    The directory location depends on where this file is:
    - In common/ (source): common/common_romanceio_static_test_data/
    - In plugin dir (after build): <plugin>/common_romanceio_static_test_data/
    """
    current_file = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file)

    # Check if we're in common/ or a plugin directory
    if os.path.basename(current_dir) == "common":
        # Source location: common/common_romanceio_static_test_data/
        return os.path.join(current_dir, "common_romanceio_static_test_data")
    # Plugin location after build: <plugin>/common_romanceio_static_test_data/
    return os.path.join(current_dir, "common_romanceio_static_test_data")


def load_static_json_file(filename: str) -> dict:
    """
    Load a static JSON file from the test data directory.

    Args:
        filename: Name of the JSON file to load

    Returns:
        Parsed JSON data as a dictionary

    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    test_data_dir = get_static_test_data_dir()
    filepath = os.path.join(test_data_dir, filename)

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Static test file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def load_static_html_file(filename: str) -> bytes:
    """
    Load a static HTML file from the test data directory.

    Args:
        filename: Name of the HTML file to load

    Returns:
        Raw HTML content as bytes

    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    test_data_dir = get_static_test_data_dir()
    filepath = os.path.join(test_data_dir, filename)

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Static test file not found: {filepath}")

    with open(filepath, "rb") as f:
        return f.read()


def get_static_book_by_name(name: str) -> Optional[StaticTestBook]:
    """
    Get a static test book by its display name.

    Args:
        name: Display name of the book (e.g., "Pride and Prejudice")

    Returns:
        StaticTestBook object or None if not found
    """
    for book in STATIC_TEST_BOOKS:
        if book.name == name:
            return book
    return None


def get_static_book_by_id(romanceio_id: str) -> Optional[StaticTestBook]:
    """
    Get a static test book by its Romance.io ID.

    Args:
        romanceio_id: Romance.io book ID

    Returns:
        StaticTestBook object or None if not found
    """
    for book in STATIC_TEST_BOOKS:
        if book.romanceio_id == romanceio_id:
            return book
    return None
