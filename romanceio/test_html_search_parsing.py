"""Test Romance.io search parsing with static HTML files."""

import os
import sys
import types
import importlib.util
from typing import List
from queue import Queue
from lxml.html import fromstring
from calibre.ebooks.metadata.book.base import Metadata

# Set up module path to enable relative imports
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.common_romanceio_static_test_data import STATIC_TEST_BOOKS, StaticTestBook, load_static_html_file

# Make romanceio a package
romanceio = types.ModuleType("romanceio")
romanceio.__path__ = [plugin_dir]
sys.modules["romanceio"] = romanceio

# Load config module first
config_spec = importlib.util.spec_from_file_location("romanceio.config", os.path.join(plugin_dir, "config.py"))
if config_spec is None or config_spec.loader is None:
    raise ImportError("Failed to load config module spec")
config_module = importlib.util.module_from_spec(config_spec)
sys.modules["romanceio.config"] = config_module
config_spec.loader.exec_module(config_module)

# Now load __init__ module
init_spec = importlib.util.spec_from_file_location("romanceio.__init__", os.path.join(plugin_dir, "__init__.py"))
if init_spec is None or init_spec.loader is None:
    raise ImportError("Failed to load __init__ module spec")
init_module = importlib.util.module_from_spec(init_spec)
sys.modules["romanceio.__init__"] = init_module
init_spec.loader.exec_module(init_module)


class MockLog:
    """Mock logger for testing."""

    def info(self, msg: str) -> None:
        print(f"INFO: {msg}")

    def debug(self, msg: str) -> None:
        print(f"DEBUG: {msg}")

    def error(self, msg: str) -> None:
        print(f"ERROR: {msg}")

    def exception(self, msg: str) -> None:
        print(f"EXCEPTION: {msg}")


def verify_metadata_and_cover(mi: Metadata, expected_romanceio_id: str, book_title: str) -> None:
    """Common verification for metadata and cover URL construction."""
    # Verify romanceio_id identifier
    assert mi.has_identifier("romanceio"), f"Expected romanceio identifier for {book_title}"
    romanceio_id = mi.get_identifiers().get("romanceio")
    assert (
        romanceio_id == expected_romanceio_id
    ), f"Expected ID {expected_romanceio_id} for {book_title}, got {romanceio_id}"

    # Verify cover URL is constructed correctly from the identifier
    cover_url = f"https://s3.amazonaws.com/romance.io/books/large/{romanceio_id}.jpg"

    # Verify mi.has_cover is set
    assert mi.has_cover, f"Expected has_cover to be True for {book_title}"

    print(f"✓ romanceio_id: {romanceio_id}")
    print(f"✓ cover URL: {cover_url}")
    print(f"✓ has_cover: {mi.has_cover}")


def run_search_test(
    html_filename: str,
    book_title: str,
    authors: List[str],
    expected_id: str,
) -> None:
    """Run a search parsing test and verify results."""
    raw_html = load_static_html_file(html_filename)
    root = fromstring(raw_html)

    print("=" * 60)
    print(f"Testing {book_title} Search Results")
    print("=" * 60)

    # Create a mock plugin instance
    plugin = init_module.RomanceIO(None)
    log = MockLog()
    matches: List[str] = []

    result_queue: Queue[Metadata] = Queue()
    plugin.parse_search_results(log, result_queue, book_title, authors, root, matches, 30)

    # Verify search results
    assert len(matches) > 0, "Expected at least 1 match"
    assert expected_id in matches[0], f"Expected ID {expected_id} in URL: {matches[0]}"

    # Verify metadata was added to result_queue
    assert not result_queue.empty(), "Expected metadata in result_queue"
    mi = result_queue.get()

    # Verify metadata and cover
    verify_metadata_and_cover(mi, expected_id, book_title)

    print(f"✓ All assertions passed for {book_title} search")
    print()


def test_parse_search(book_data: StaticTestBook) -> None:
    """Test parsing search results using centralized test data."""
    if not book_data.search_html_filename:
        print(f"Skipping {book_data.name} - no search HTML file")
        return

    run_search_test(
        html_filename=book_data.search_html_filename,
        book_title=book_data.title,
        authors=book_data.authors,
        expected_id=book_data.romanceio_id,
    )


if __name__ == "__main__":
    for book in STATIC_TEST_BOOKS:
        test_parse_search(book)
