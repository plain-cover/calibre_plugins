"""
Shared test utilities for Romance.io Fields plugin tests.
"""

import os
import sys
import types
import importlib.util
import functools
from typing import Any, Dict, List, Optional, Callable


def setup_test_environment(plugin_name: str = "romanceio_fields") -> Dict[str, Any]:
    """
    Set up the test environment with common module imports and paths.
    This eliminates duplicated setup code across test files.

    Args:
        plugin_name: Name of the plugin directory (default: "romanceio_fields")

    Returns:
        Dict with common modules and functions:
            - plugin_dir: Path to plugin directory
            - parent_dir: Path to parent directory
            - common_dir: Path to common directory
            - config_module: Config module
            - fetch_helper_module: Fetch helper module from common
            - common_search_module: Common search module
            - fetch_page: Wrapper function for fetch_page
    """
    # Set up module paths
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(plugin_dir)
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    # Import load_plugin_module from common.test_data
    # We need to do this before setting up fake packages
    sys_path_snapshot = sys.path.copy()
    try:
        from common.test_data import load_plugin_module
    except ImportError:
        sys.path = sys_path_snapshot
        # If that fails, set up path and try again
        common_dir_temp = os.path.join(parent_dir, "common")
        if common_dir_temp not in sys.path:
            sys.path.insert(0, common_dir_temp)
        from common.test_data import load_plugin_module

    # Make calibre_plugins a package
    calibre_plugins = types.ModuleType("calibre_plugins")
    calibre_plugins.__path__ = [parent_dir]
    sys.modules["calibre_plugins"] = calibre_plugins

    # Make calibre_plugins.common a package
    common_dir = os.path.join(parent_dir, "common")
    common = types.ModuleType("calibre_plugins.common")
    common.__path__ = [common_dir]
    sys.modules["calibre_plugins.common"] = common

    # Make romanceio_fields a package (or other plugin)
    plugin_module = types.ModuleType(plugin_name)
    plugin_module.__path__ = [plugin_dir]
    sys.modules[plugin_name] = plugin_module

    fetch_helper_spec = importlib.util.spec_from_file_location(
        "calibre_plugins.common.common_romanceio_fetch_helper",
        os.path.join(common_dir, "common_romanceio_fetch_helper.py"),
    )
    if fetch_helper_spec is None:
        raise ImportError("Could not load common_romanceio_fetch_helper module spec")
    fetch_helper_module = importlib.util.module_from_spec(fetch_helper_spec)
    sys.modules["calibre_plugins.common.common_romanceio_fetch_helper"] = fetch_helper_module
    if fetch_helper_spec.loader is None:
        raise ImportError("fetch_helper_spec.loader is None")
    fetch_helper_spec.loader.exec_module(fetch_helper_module)

    # Load config module
    config_module = load_plugin_module(f"{plugin_name}.config", "config.py", plugin_dir)

    # Load common_romanceio_search module
    common_search_spec = importlib.util.spec_from_file_location(
        f"{plugin_name}.common_romanceio_search", os.path.join(plugin_dir, "common_romanceio_search.py")
    )
    if common_search_spec is None:
        raise ImportError("Could not load common_romanceio_search module spec")
    common_search_module = importlib.util.module_from_spec(common_search_spec)
    sys.modules[f"{plugin_name}.common_romanceio_search"] = common_search_module
    if common_search_spec.loader is None:
        raise ImportError("common_search_spec.loader is None")
    common_search_spec.loader.exec_module(common_search_module)

    # Create fetch_page wrapper
    fetch_page_base = fetch_helper_module.fetch_page

    def fetch_page(url, wait_for_element=None, not_found_marker=None, secondary_wait_element=None, max_wait=30):
        """Wrapper to add plugin_name for tests"""
        return fetch_page_base(
            url,
            plugin_name,
            wait_for_element=wait_for_element,
            not_found_marker=not_found_marker,
            secondary_wait_element=secondary_wait_element,
            max_wait=max_wait,
        )

    # Create pre-configured get_romanceio_id function
    # This will be bound later once get_romanceio_id is available
    search_func = common_search_module.search_for_romanceio_id

    return {
        "plugin_dir": plugin_dir,
        "parent_dir": parent_dir,
        "common_dir": common_dir,
        "config_module": config_module,
        "fetch_helper_module": fetch_helper_module,
        "common_search_module": common_search_module,
        "fetch_page": fetch_page,
        "load_plugin_module": load_plugin_module,
        "search_for_romanceio_id": search_func,
        "field_constants": {
            "steam": config_module.FIELD_STEAM_RATING,
            "star_rating": config_module.FIELD_STAR_RATING,
            "rating_count": config_module.FIELD_RATING_COUNT,
            "tags": config_module.FIELD_ROMANCE_TAGS,
        },
    }


def get_romanceio_id(
    search_for_romanceio_id_func: Callable,
    fetch_page_func: Callable,
    romanceio_id: Optional[str] = None,
    title: Optional[str] = None,
    authors: Optional[list] = None,
) -> Optional[str]:
    """
    Get Romance.io ID for a book - either use provided ID or search for it.

    This is a simplified version for testing. Unlike jobs.py which uses search_with_fallback
    to try multiple search methods, this takes a specific search function as a parameter.

    Args:
        search_for_romanceio_id_func: The search function to use
        fetch_page_func: The fetch page function to use
        romanceio_id: The Romance.io book identifier (optional)
        title: Book title (optional if romanceio_id provided)
        authors: List of authors (optional)

    Returns:
        romanceio_id string, or None if not found
    """
    # If we already have the ID, just return it
    if romanceio_id:
        return romanceio_id

    # Otherwise search for it
    if not title:
        return None

    print(f"\nSearching for Romance.io ID for: {title}")
    if authors:
        print(f"  Authors: {', '.join(authors)}")

    romanceio_id = search_for_romanceio_id_func(title, authors, fetch_page_func, log_func=print)

    if romanceio_id:
        print(f"\n✓ Found Romance.io ID: {romanceio_id}\n")
    else:
        print("\nCould not find Romance.io ID")

    return romanceio_id


def create_test_book_fields_func(
    fetch_and_parse_func: Callable[[str, bool], tuple],
    env: Dict[str, Any],
) -> Callable:
    """
    Create a pre-configured test_book_fields function.

    Args:
        fetch_and_parse_func: Function that fetches and parses data (JSON or HTML)
        env: Environment dict from setup_test_environment

    Returns:
        Configured test_book_fields function
    """
    # Extract what we need from env
    get_romanceio_id_func = create_romanceio_id_getter(
        env["search_for_romanceio_id"],
        env["fetch_page"],
    )
    field_constants = env["field_constants"]
    tag_delimiter = env["config_module"].TAG_DELIMITER

    def test_book_fields(
        romanceio_id: Optional[str] = None,
        title: Optional[str] = None,
        authors: Optional[list] = None,
        expected_fields: Optional[dict] = None,
        fields_to_test: Optional[list] = None,
    ) -> bool:
        """Test downloading Romance.io fields for a specific book."""
        return test_book_fields_generic(
            romanceio_id,
            title,
            authors,
            expected_fields,
            fields_to_test,
            get_romanceio_id_func,
            fetch_and_parse_func,
            field_constants,
            tag_delimiter,
        )

    return test_book_fields


def run_test_suite(
    test_suite_name: str,
    fetch_and_parse_func: Callable[[str, bool], tuple],
    env: Dict[str, Any],
    test_books: List[Any],
) -> bool:
    """
    Run a complete test suite with minimal configuration.

    This is a convenience function that creates test_book_fields and runs all tests.

    Args:
        test_suite_name: Name of test suite for display
        fetch_and_parse_func: Function that fetches and parses data (JSON or HTML)
        env: Environment dict from setup_test_environment
        test_books: List of test book objects

    Returns:
        True if all tests passed, False otherwise
    """
    # Create the test_book_fields function
    test_book_fields = create_test_book_fields_func(fetch_and_parse_func, env)

    # Run all tests
    return run_all_tests(
        test_suite_name=test_suite_name,
        test_books=test_books,
        test_book_fields_func=test_book_fields,
        field_constants=env["field_constants"],
        tag_delimiter=env["config_module"].TAG_DELIMITER,
    )


def create_romanceio_id_getter(
    search_for_romanceio_id_func: Callable,
    fetch_page_func: Callable,
) -> Callable:
    """
    Create a pre-configured get_romanceio_id function with search and fetch functions bound.

    Args:
        search_for_romanceio_id_func: The search function to use
        fetch_page_func: The fetch page function to use

    Returns:
        Configured function that only needs romanceio_id, title, and authors parameters
    """
    return functools.partial(
        get_romanceio_id,
        search_for_romanceio_id_func,
        fetch_page_func,
    )


def convert_parsed_fields_to_results(
    parsed_fields: Dict[str, Any],
    fields_to_test: List[str],
    field_steam_rating: str,
    field_star_rating: str,
    field_rating_count: str,
    field_romance_tags: str,
    tag_delimiter: str,
) -> Dict[str, Any]:
    """
    Convert parsed fields from JSON or HTML into result format expected by tests.

    Args:
        parsed_fields: Dict containing parsed metadata (steam_rating, star_rating, rating_count, tags)
        fields_to_test: List of field constants to include in results
        field_steam_rating: Field constant for steam rating
        field_star_rating: Field constant for star rating
        field_rating_count: Field constant for rating count
        field_romance_tags: Field constant for romance tags
        tag_delimiter: Delimiter to join tags

    Returns:
        Dict with formatted results ready for validation
    """
    results: Dict[str, Any] = {}

    for field in fields_to_test:
        if field == field_steam_rating and "steam_rating" in parsed_fields:
            value = parsed_fields["steam_rating"]
            if value is not None:
                results[field_steam_rating] = int(round(value)) if isinstance(value, float) else int(value)
        elif field == field_star_rating and "star_rating" in parsed_fields:
            value = parsed_fields["star_rating"]
            if value is not None:
                results[field_star_rating] = round(value, 2)
        elif field == field_rating_count and "rating_count" in parsed_fields:
            results[field_rating_count] = parsed_fields["rating_count"]
        elif field == field_romance_tags and "tags" in parsed_fields:
            tags = parsed_fields["tags"]
            if isinstance(tags, list) and len(tags) > 0:
                filtered_tags = [str(tag) for tag in tags[:50]]
                tag_string: str = tag_delimiter.join(filtered_tags)
                results[field_romance_tags] = tag_string

    return results


def test_book_fields_generic(
    romanceio_id: Optional[str],
    title: Optional[str],
    authors: Optional[list],
    expected_fields: Optional[dict],
    fields_to_test: Optional[list],
    get_romanceio_id_func: Callable,
    fetch_and_parse_func: Callable[[str, bool], tuple],
    field_constants: Dict[str, str],
    tag_delimiter: str,
) -> bool:
    """
    Generic test function for downloading and validating Romance.io fields.

    Args:
        romanceio_id: The Romance.io book identifier (optional if title/authors provided)
        title: Book title (for display/logging only, optional)
        authors: List of authors (for display/logging only, optional)
        expected_fields: Dict of field names to expected values (optional)
        fields_to_test: List of field names to download (defaults to all)
        get_romanceio_id_func: Function to get romanceio_id
        fetch_and_parse_func: Function that fetches and parses data, returns (parsed_fields, is_negative_test_result)
        field_constants: Dict mapping field names to field constants
        tag_delimiter: Delimiter for tags

    Returns:
        True if test passed, False otherwise
    """
    print("=" * 80)
    if title and authors:
        print(f"Testing: {title} by {', '.join(authors)}")
    elif title:
        print(f"Testing: {title}")
    else:
        print(f"Testing book with Romance.io ID: {romanceio_id}")
    print("=" * 80)

    romanceio_id = get_romanceio_id_func(romanceio_id, title, authors)

    is_negative_test: bool = bool(expected_fields and expected_fields.get("romanceio_id") is None)

    # If no ID found and it's a negative test, that's expected
    if not romanceio_id:
        if is_negative_test:
            print("✓ PASSED: Correctly found no match (as expected)")
            return True
        print("❌ FAILED: Could not determine Romance.io ID")
        return False

    print(f"Romance.io ID: {romanceio_id}\n")

    if fields_to_test is None:
        fields_to_test = [
            field_constants["steam"],
            field_constants["star_rating"],
            field_constants["rating_count"],
            field_constants["tags"],
        ]

    try:
        parsed_fields, negative_test_result = fetch_and_parse_func(romanceio_id, is_negative_test)

        if negative_test_result is not None:
            return negative_test_result

        results = convert_parsed_fields_to_results(
            parsed_fields,
            fields_to_test,
            field_constants["steam"],
            field_constants["star_rating"],
            field_constants["rating_count"],
            field_constants["tags"],
            tag_delimiter,
        )

        # Display and validate results
        return display_and_validate_results(
            results,
            fields_to_test,
            field_constants["tags"],
            tag_delimiter,
            romanceio_id,
            title,
            expected_fields,
            is_negative_test,
        )

    except Exception as e:  # pylint: disable=broad-except
        print(f"\n❌ EXCEPTION testing {title}: {e}")
        import traceback

        traceback.print_exc()
        return False


def display_and_validate_results(
    results: Dict[str, Any],
    fields_to_test: List[str],
    tag_field: str,
    tag_delimiter: str,
    romanceio_id: Optional[str],
    title: Optional[str],
    expected_fields: Optional[Dict[str, Any]],
    is_negative_test: bool = False,
) -> bool:
    """
    Display test results and validate against expected fields if provided.

    Args:
        results: Dict of field names to values
        fields_to_test: List of field names that were tested
        tag_field: The field name for tags
        tag_delimiter: Delimiter used for tag strings
        romanceio_id: The romanceio_id being tested
        title: Book title for display
        expected_fields: Dict of field names to expected values (optional)
        is_negative_test: Whether this is a negative test (expecting no match)

    Returns:
        True if validation passed (or no validation needed), False otherwise
    """
    if not results:
        print(f"❌ FAILED: No results returned for {title}")
        return False

    # Display results
    display_test_results(results, fields_to_test, tag_field, tag_delimiter)

    if expected_fields:
        return validate_expected_fields(expected_fields, results, romanceio_id, title, is_negative_test)

    # No validation, just check if we got results
    print(f"\n✓ Successfully downloaded fields for {title}")
    return True


def display_test_results(
    results: Dict[str, Any],
    fields_to_test: List[str],
    tag_field: str,
    tag_delimiter: str,
) -> None:
    """
    Display test results in a formatted way.

    Args:
        results: Dict of field names to values
        fields_to_test: List of field names that were tested
        tag_field: The field name for tags
        tag_delimiter: Delimiter used for tag strings
    """
    print("\nResults:")
    for field in fields_to_test:
        if field in results:
            value = results[field]
            if field == tag_field and value:
                tags = value.split(tag_delimiter)
                print(f"  {field}: {len(tags)} tags - {tags[:5]}...")
            else:
                print(f"  {field}: {value}")
        else:
            print(f"  {field}: (not found)")


def validate_expected_fields(
    expected_fields: Dict[str, Any],
    results: Dict[str, Any],
    romanceio_id: Optional[str],
    title: Optional[str],
    is_negative_test: bool = False,
) -> bool:
    """
    Validate expected fields against actual results.

    Args:
        expected_fields: Dict of field names to expected values
        results: Dict of actual field values
        romanceio_id: The romanceio_id being tested
        title: Book title (for display)
        is_negative_test: Whether this is a negative test (expecting no match)

    Returns:
        True if all validations passed, False otherwise
    """
    print("\nValidating expected values:")
    all_passed = True

    # If it's a negative test and we got invalid_romanceio_id flag, that's a pass
    if is_negative_test and results.get("invalid_romanceio_id"):
        print("  ✓ romanceio_id: None (invalid ID detected as expected)")
        print("\n✓ PASSED: Correctly detected invalid ID (as expected)")
        return True

    for field, expected_value in expected_fields.items():
        actual_value: Any
        if field == "romanceio_id":
            # Special handling for romanceio_id validation
            # If results indicate invalid ID, romanceio_id should be None
            if results.get("invalid_romanceio_id"):
                actual_value = None
            else:
                actual_value = romanceio_id
        else:
            actual_value = results.get(field)

        if callable(expected_value):
            # Allow validators (e.g., lambda x: x > 0)
            passed = expected_value(actual_value)
            status = "✓" if passed else "❌"

            # Try to provide helpful info about what was expected
            validator_repr = str(expected_value)
            if "lambda" in validator_repr:
                # For common patterns, provide readable descriptions
                # Try calling with test values to determine the condition
                try:
                    if expected_value(1) and not expected_value(0):
                        validator_desc = "> 0"
                    elif expected_value(0) and not expected_value(-1):
                        validator_desc = ">= 0"
                    elif expected_value(-1) and not expected_value(0):
                        validator_desc = "< 0"
                    else:
                        validator_desc = "validator function"
                except Exception:  # pylint: disable=broad-except
                    validator_desc = "validator function"
            else:
                validator_desc = "validator function"

            if not passed:
                print(f"  {status} {field}: expected {validator_desc}, got {actual_value}")
                all_passed = False
            else:
                print(f"  {status} {field}: {actual_value} (expected {validator_desc})")
        else:
            # Exact match
            passed = actual_value == expected_value
            status = "✓" if passed else "❌"
            if not passed:
                print(f"  {status} {field}: expected {expected_value}, got {actual_value}")
                all_passed = False
            else:
                print(f"  {status} {field}: {actual_value} (expected {expected_value})")

    if all_passed:
        print(f"\n✓ All tests passed for {title}")
    else:
        print(f"\n❌ Some tests failed for {title}")
    return all_passed


class TestCase:
    """Represents a test case for downloading Romance.io fields."""

    def __init__(
        self,
        romanceio_id: Optional[str] = None,
        title: Optional[str] = None,
        authors: Optional[List[str]] = None,
        expected_fields: Optional[Dict[str, Any]] = None,
    ):
        self.romanceio_id = romanceio_id
        self.title = title
        self.authors = authors
        self.expected_fields = expected_fields or {}


def run_all_tests(
    test_suite_name: str,
    test_books: List[Any],
    test_book_fields_func: Callable,
    field_constants: Dict[str, str],
    tag_delimiter: str,
    max_retries: int = 5,
) -> bool:
    """
    Run all book tests with retry logic.

    This is a generic test runner that can be used by both HTML and JSON API tests.

    Args:
        test_suite_name: Name of the test suite (e.g., "Romance.io HTML Fields Download Tests")
        test_books: List of test book data from TEST_BOOKS
        test_book_fields_func: Function to test a single book
            (must accept romanceio_id, title, authors, expected_fields)
        field_constants: Dict mapping generic field names to plugin-specific constants
            Expected keys: "steam", "star_rating", "rating_count", "tags"
        tag_delimiter: Delimiter used for tag strings
        max_retries: Maximum number of retry attempts per test (default: 3)

    Returns:
        True if all tests passed, False otherwise
    """
    print("\n" + "=" * 80)
    print(test_suite_name)
    print("=" * 80 + "\n")

    # Build test cases from shared test data
    test_cases = []
    for book in test_books:
        # Map generic field names to actual field constants
        expected_fields = {}
        for field_name, validator in book.expected_fields.items():
            if field_name == "romanceio_id":
                expected_fields["romanceio_id"] = validator
            elif field_name == "steam":
                expected_fields[field_constants["steam"]] = validator
            elif field_name == "star_rating":
                expected_fields[field_constants["star_rating"]] = validator
            elif field_name == "rating_count":
                expected_fields[field_constants["rating_count"]] = validator
            elif field_name == "tags":
                # Tags validator takes delimiter parameter, wrap it
                if callable(validator):
                    expected_fields[field_constants["tags"]] = lambda x, v=validator: v(x, tag_delimiter)
                else:
                    expected_fields[field_constants["tags"]] = validator

        test_cases.append(
            TestCase(
                romanceio_id=book.romanceio_id,
                title=book.title,
                authors=book.authors,
                expected_fields=expected_fields,
            )
        )

    passed = 0
    failed = 0
    retry_count = 0

    for i, test_case in enumerate(test_cases):
        print(f"\nTest {i+1}/{len(test_cases)}")

        # Retry logic for this specific test
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                print(f"  Retry attempt {attempt}/{max_retries}")

            try:
                result = test_book_fields_func(
                    romanceio_id=test_case.romanceio_id,
                    title=test_case.title,
                    authors=test_case.authors,
                    expected_fields=test_case.expected_fields,
                )
            except (RuntimeError, OSError, TimeoutError) as e:
                print(f"\n  ✗ Exception on attempt {attempt}: {e}")
                result = False

            if result:
                passed += 1
                if attempt > 1:
                    retry_count += 1
                break
            if attempt < max_retries:
                print(f"  ✗ Failed (attempt {attempt}), retrying in 2 seconds...")
                import time

                time.sleep(2)
            else:
                print(f"  ✗ Failed after {max_retries} attempts")
                failed += 1

        print()

    print("=" * 80)
    print(f"Test Results: {passed} passed, {failed} failed out of {passed + failed} total")
    if retry_count > 0:
        print(f"Note: {retry_count} test(s) required retries to pass")
    print("=" * 80)

    return failed == 0
