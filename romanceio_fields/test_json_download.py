"""
Test Romance.io JSON API download for various books.

This is an integration test that downloads live JSON API data from Romance.io and validates
JSON field extraction. It requires an active internet connection.

For unit tests that use static files and don't require internet, see:
- test_json_parsing.py (static JSON files)
For HTML live download tests, see:
- test_html_fields_download.py (live HTML scraping)

To run these tests:
    calibre-debug -e test_json_download.py
"""

import os
import sys
import importlib.util

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

# Track whether the /json/books endpoint returned 404 this session so we skip
# subsequent books immediately rather than hammering a known-dead endpoint.
# Using a dict (mutable container) avoids needing a global statement in the closure.
_json_endpoint_state = {"dead": False}


def fetch_and_parse_json(romanceio_id: str, is_negative_test: bool) -> tuple:
    """Fetch and parse JSON data for a book.

    Returns:
        Tuple of (parsed_fields, negative_test_result)
        negative_test_result is True/False if test should end early, None otherwise
    """
    load_plugin_module = env["load_plugin_module"]

    parse_json = load_plugin_module("romanceio_fields.parse_json", "parse_json.py", env["plugin_dir"])

    common_json_api_spec = importlib.util.spec_from_file_location(
        "calibre_plugins.common.common_romanceio_json_api",
        os.path.join(env["common_dir"], "common_romanceio_json_api.py"),
    )
    if common_json_api_spec is None or common_json_api_spec.loader is None:
        raise ImportError("Could not load common_romanceio_json_api module spec")
    common_json_api = importlib.util.module_from_spec(common_json_api_spec)
    sys.modules["calibre_plugins.common.common_romanceio_json_api"] = common_json_api
    common_json_api_spec.loader.exec_module(common_json_api)

    parse_fields_from_json = parse_json.parse_fields_from_json
    get_book_details_json = common_json_api.get_book_details_json
    json_api_endpoint_error = common_json_api.JsonApiEndpointError

    print(f"Fetching JSON API data for {romanceio_id}...")
    if _json_endpoint_state["dead"]:
        print("⚠️  SKIPPED: JSON API /books endpoint returned 404 earlier this session")
        return (None, True)
    try:
        book_json = get_book_details_json(romanceio_id, log_func=print, timeout=30)
    except json_api_endpoint_error as e:
        print(f"⚠️  SKIPPED: {e}")
        _json_endpoint_state["dead"] = True
        return (None, True)

    if book_json is None:
        print(f"○ JSON API returned no data for {romanceio_id}")
        if is_negative_test:
            print("✓ PASSED: Correctly detected no match (as expected)")
            return (None, True)
        print(f"❌ FAILED: JSON API returned no data for {romanceio_id}")
        return (None, False)

    print("✓ JSON API data fetched successfully")
    parsed_fields = parse_fields_from_json(book_json)
    return (parsed_fields, None)


if __name__ == "__main__":
    success = run_test_suite(
        test_suite_name="Romance.io JSON API Download Tests",
        fetch_and_parse_func=fetch_and_parse_json,
        env=env,
        test_books=TEST_BOOKS,
    )
    sys.exit(0 if success else 1)
