"""
Test Romance.io HTML fields download for various books.

This is an integration test that downloads live HTML data from Romance.io and validates
HTML field extraction. It requires an active internet connection.

For unit tests that use static files and don't require internet, see:
- test_html_fields_parsing.py (static HTML files)
For JSON API live download tests, see:
- test_json_download.py (live JSON API)

To run these tests:
    calibre-debug -e test_html_fields_download.py
"""

import os
import sys

# Set up module path to enable relative imports
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from test_utils import (  # type: ignore[import-not-found]  # pylint: disable=import-error
    setup_test_environment,
    run_test_suite,
)
from common.test_data import TEST_BOOKS

env = setup_test_environment("romanceio_fields")


def fetch_and_parse_html(romanceio_id: str, is_negative_test: bool) -> tuple:
    """Fetch and parse HTML data for a book.

    Returns:
        Tuple of (parsed_fields, negative_test_result)
        negative_test_result is True/False if test should end early, None otherwise
    """
    load_plugin_module = env["load_plugin_module"]

    parse_html = load_plugin_module("romanceio_fields.parse_html", "parse_html.py", env["plugin_dir"])
    fetch_helper = load_plugin_module("romanceio_fields.fetch_helper", "fetch_helper.py", env["plugin_dir"])

    parse_fields_from_html = parse_html.parse_fields_from_html
    fetch_romanceio_book_page = fetch_helper.fetch_romanceio_book_page

    print(f"Fetching HTML page for {romanceio_id}...")
    url = f"https://www.romance.io/books/{romanceio_id}"
    raw_html, is_valid = fetch_romanceio_book_page(url, log=print)

    if not is_valid:
        print(f"○ HTML fetch returned invalid ID for {romanceio_id}")
        if is_negative_test:
            print("✓ PASSED: Correctly detected invalid ID (as expected)")
            return (None, True)
        print(f"❌ FAILED: Invalid Romance.io ID {romanceio_id}")
        return (None, False)

    if not raw_html:
        print(f"❌ FAILED: Failed to fetch HTML for {romanceio_id}")
        return (None, False)

    print("✓ HTML page fetched successfully")
    from lxml.html import fromstring

    root = fromstring(raw_html)
    parsed_fields = parse_fields_from_html(root, max_tags=50)
    return (parsed_fields, None)


if __name__ == "__main__":
    success = run_test_suite(
        test_suite_name="Romance.io HTML Fields Download Tests",
        fetch_and_parse_func=fetch_and_parse_html,
        env=env,
        test_books=TEST_BOOKS,
    )
    sys.exit(0 if success else 1)
