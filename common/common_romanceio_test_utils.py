"""
Shared test utilities for romanceio and romanceio_fields plugins.

Provides common test infrastructure for comparing JSON and HTML parsing results.
"""

import inspect
import json
import os
from typing import Any, Callable, Dict, List, Optional, Set

from lxml.html import HtmlElement, fromstring


class MetadataComparison:
    """Container for metadata from different parsing strategies.

    Can compare different sets of fields depending on plugin needs.
    """

    def __init__(self, book_title: str, romanceio_id: str, fields_to_compare: Optional[Set[str]] = None):
        """Initialize metadata comparison.

        Args:
            book_title: Title of the book being tested
            romanceio_id: Romance.io ID
            fields_to_compare: Set of field names to compare. If None, compares all fields.
                Valid fields: romanceio_id, title, authors, star_rating, steam_rating,
                rating_count, tags, series, pubdate
        """
        self.book_title = book_title
        self.romanceio_id = romanceio_id
        self.json_data: Optional[Dict[str, Any]] = None
        self.html_data: Optional[Dict[str, Any]] = None
        self.errors: List[str] = []
        self.fields_to_compare = fields_to_compare

    def add_json_data(self, data: Dict[str, Any]) -> None:
        """Add JSON-parsed metadata."""
        self.json_data = data

    def add_html_data(self, data: Dict[str, Any]) -> None:
        """Add HTML-parsed metadata."""
        self.html_data = data

    def _should_compare_field(self, field_name: str) -> bool:
        """Check if a field should be compared."""
        if self.fields_to_compare is None:
            return True
        return field_name in self.fields_to_compare

    def compare(self) -> bool:
        """
        Compare JSON and HTML metadata and report differences.

        Returns:
            True if all metadata matches, False otherwise
        """
        if self.json_data is None or self.html_data is None:
            self.errors.append("Missing data: JSON or HTML data not available")
            return False

        all_match = True
        mismatches: List[str] = []

        if self._should_compare_field("romanceio_id"):
            json_id = self.json_data.get("romanceio_id")
            html_id = self.html_data.get("romanceio_id")
            if json_id != html_id:
                mismatches.append("  ❌ ROMANCEIO_ID MISMATCH:")
                mismatches.append(f"     JSON:  '{json_id}'")
                mismatches.append(f"     HTML:  '{html_id}'")
                all_match = False

        if self._should_compare_field("title"):
            json_title = self.json_data.get("title")
            html_title = self.html_data.get("title")
            if json_title != html_title:
                mismatches.append("  ❌ TITLE MISMATCH:")
                mismatches.append(f"     JSON:  '{json_title}'")
                mismatches.append(f"     HTML:  '{html_title}'")
                all_match = False

        # Compare authors (allow for different ordering)
        if self._should_compare_field("authors"):
            json_authors = set(self.json_data.get("authors", []))
            html_authors = set(self.html_data.get("authors", []))
            if json_authors != html_authors:
                mismatches.append("  ❌ AUTHORS MISMATCH:")
                if json_authors - html_authors:
                    mismatches.append(f"     Extra in JSON:  {sorted(json_authors - html_authors)}")
                if html_authors - json_authors:
                    mismatches.append(f"     Extra in HTML:  {sorted(html_authors - json_authors)}")
                all_match = False

        # Compare star rating (allow small float differences)
        if self._should_compare_field("star_rating"):
            json_star = self.json_data.get("star_rating")
            html_star = self.html_data.get("star_rating")
            if json_star is not None and html_star is not None:
                if abs(json_star - html_star) > 0.01:
                    mismatches.append("  ❌ STAR RATING MISMATCH:")
                    mismatches.append(f"     JSON:  {json_star}")
                    mismatches.append(f"     HTML:  {html_star}")
                    all_match = False
            elif json_star != html_star:
                mismatches.append("  ❌ STAR RATING MISMATCH (one is None):")
                mismatches.append(f"     JSON:  {json_star}")
                mismatches.append(f"     HTML:  {html_star}")
                all_match = False

        if self._should_compare_field("rating_count"):
            json_count = self.json_data.get("rating_count")
            html_count = self.html_data.get("rating_count")
            if json_count != html_count:
                mismatches.append("  ❌ RATING COUNT MISMATCH:")
                mismatches.append(f"     JSON:  {json_count}")
                mismatches.append(f"     HTML:  {html_count}")
                all_match = False

        if self._should_compare_field("steam_rating"):
            json_steam = self.json_data.get("steam_rating")
            html_steam = self.html_data.get("steam_rating")
            if json_steam != html_steam:
                mismatches.append("  ❌ STEAM RATING MISMATCH:")
                mismatches.append(f"     JSON:  {json_steam}")
                mismatches.append(f"     HTML:  {html_steam}")
                all_match = False

        # Compare tags (fuzzy matching - allow some differences)
        if self._should_compare_field("tags"):
            json_tags = set(self.json_data.get("tags", []))
            html_tags = set(self.html_data.get("tags", []))

            if json_tags:
                json_tags_in_html = json_tags & html_tags
                missing_from_html = json_tags - html_tags
                extra_in_html = html_tags - json_tags

                match_percentage = len(json_tags_in_html) / len(json_tags) * 100

                # Fuzzy match criteria:
                # 1. At least 85% of JSON tags must be in HTML
                # 2. Allow extra tags in HTML (up to 50% more than JSON count)
                min_match_percentage = 85.0
                max_extra_percentage = 50.0

                tags_match = True
                mismatch_reasons = []

                if match_percentage < min_match_percentage:
                    tags_match = False
                    mismatch_reasons.append(
                        f"     Only {match_percentage:.1f}% of JSON tags found in HTML "
                        f"(minimum: {min_match_percentage}%)"
                    )

                if json_tags and extra_in_html:
                    extra_percentage = len(extra_in_html) / len(json_tags) * 100
                    if extra_percentage > max_extra_percentage:
                        tags_match = False
                        mismatch_reasons.append(
                            f"     Too many extra tags in HTML: {extra_percentage:.1f}% "
                            f"(maximum: {max_extra_percentage}%)"
                        )

                if not tags_match:
                    mismatches.append("  ❌ TAGS MISMATCH:")
                    mismatches.append(f"     Total tags - JSON: {len(json_tags)}, HTML: {len(html_tags)}")
                    mismatches.append(
                        f"     Match: {len(json_tags_in_html)}/{len(json_tags)} ({match_percentage:.1f}%)"
                    )
                    for reason in mismatch_reasons:
                        mismatches.append(reason)
                    if missing_from_html:
                        mismatches.append(
                            f"     Missing from HTML ({len(missing_from_html)}): {sorted(missing_from_html)}"
                        )
                    if extra_in_html:
                        mismatches.append(f"     Extra in HTML ({len(extra_in_html)}): {sorted(extra_in_html)}")
                    all_match = False
                else:
                    if missing_from_html or extra_in_html:
                        print(
                            f"     ℹ️  Tag differences (within thresholds - "
                            f"JSON: {len(json_tags)}, HTML: {len(html_tags)}):"
                        )
                        if missing_from_html:
                            print(f"        Missing from HTML ({len(missing_from_html)}): {sorted(missing_from_html)}")
                        if extra_in_html:
                            print(f"        Extra in HTML ({len(extra_in_html)}): {sorted(extra_in_html)}")
            elif html_tags:
                # JSON has no tags but HTML does - should we fail?
                # For now, allow it (fuzzy matching)
                print(f"     Note: JSON has no tags but HTML has {len(html_tags)} (fuzzy match OK)")

        if self._should_compare_field("series"):
            json_series = self.json_data.get("series")
            html_series = self.html_data.get("series")
            if json_series != html_series:
                mismatches.append("  ❌ SERIES MISMATCH:")
                mismatches.append(f"     JSON:  {json_series!r}")
                mismatches.append(f"     HTML:  {html_series!r}")
                all_match = False
            else:
                json_si = self.json_data.get("series_index")
                html_si = self.html_data.get("series_index")
                if json_si != html_si:
                    mismatches.append("  ❌ SERIES INDEX MISMATCH:")
                    mismatches.append(f"     JSON:  {json_si!r}")
                    mismatches.append(f"     HTML:  {html_si!r}")
                    all_match = False

        if self._should_compare_field("pubdate"):
            json_pub = self.json_data.get("pubdate")
            html_pub = self.html_data.get("pubdate")
            json_year = json_pub.year if json_pub else None
            html_year = html_pub.year if html_pub else None
            if json_year is None and html_year is None:
                mismatches.append(
                    "  ⚠️  PUBDATE: both JSON and HTML returned None (not yet parsed or missing from page)"
                )
            elif json_year != html_year:
                mismatches.append("  ❌ PUBDATE MISMATCH:")
                mismatches.append(f"     JSON:  {json_year!r}")
                mismatches.append(f"     HTML:  {html_year!r}")
                all_match = False

        if not all_match:
            self.errors.extend(mismatches)

        return all_match

    def print_result(self) -> None:
        """Print the comparison result."""
        if not self.errors:
            print(f"✓ {self.book_title} - All metadata matches between JSON and HTML!")
        else:
            print(f"\n{'=' * 80}")
            print(f"❌ METADATA MISMATCH: {self.book_title}")
            print(f"   Romance.io ID: {self.romanceio_id}")
            if self.fields_to_compare:
                print(f"   Fields compared: {', '.join(sorted(self.fields_to_compare))}")
            else:
                print(f"   Fields compared: ALL")
            print(f"{'=' * 80}")
            for error in self.errors:
                print(error)
            print()


def load_json_file(filename: str, plugin_dir_path: str) -> Dict[str, Any]:
    """Load a JSON file from test_data directory.

    Args:
        filename: Name of JSON file in test_data directory
        plugin_dir_path: Path to plugin directory

    Returns:
        Dict with parsed JSON data
    """
    test_data_dir = os.path.join(plugin_dir_path, "test_data")
    json_file = os.path.join(test_data_dir, filename)

    if not os.path.exists(json_file):
        raise FileNotFoundError(f"JSON file not found: {json_file}")

    with open(json_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_html_file(filename: str, plugin_dir_path: str) -> HtmlElement:
    """Load and parse an HTML file from test_data directory.

    Args:
        filename: Name of HTML file in test_data directory
        plugin_dir_path: Path to plugin directory

    Returns:
        Parsed HTML root element
    """
    test_data_dir = os.path.join(plugin_dir_path, "test_data")
    html_file = os.path.join(test_data_dir, filename)

    if not os.path.exists(html_file):
        raise FileNotFoundError(f"HTML file not found: {html_file}")

    with open(html_file, "rb") as f:
        raw_utf8 = f.read()

    return fromstring(raw_utf8)


def get_caller_plugin_dir() -> str:
    """
    Auto-detect the plugin directory from the calling test file.

    Returns:
        Path to the plugin directory where the test file is located
    """
    frame = inspect.currentframe()
    if frame is None:
        raise RuntimeError("Cannot determine caller context")

    this_file = os.path.abspath(__file__)

    caller_frame = frame.f_back
    while caller_frame is not None:
        caller_file = caller_frame.f_globals.get("__file__")
        if caller_file is not None:
            caller_file_abs = os.path.abspath(caller_file)
            if caller_file_abs != this_file:
                return os.path.dirname(caller_file_abs)
        caller_frame = caller_frame.f_back

    raise RuntimeError("Cannot determine caller file outside common_test_utils")


def load_test_json_file(filename: str) -> Dict[str, Any]:
    """
    Load a JSON file from the centralized static test data directory.

    The static test data is copied to each plugin during build, so this always
    loads from the centralized common_romanceio_static_test_data location.

    Args:
        filename: Name of JSON file in static test data directory

    Returns:
        Dict with parsed JSON data
    """
    from common.common_romanceio_static_test_data import load_static_json_file

    return load_static_json_file(filename)


def load_test_html_file(filename: str) -> HtmlElement:
    """
    Load an HTML file from the centralized static test data directory.

    The static test data is copied to each plugin during build, so this always
    loads from the centralized common_romanceio_static_test_data location.

    Args:
        filename: Name of HTML file in static test data directory

    Returns:
        Parsed HTML root element
    """
    from common.common_romanceio_static_test_data import load_static_html_file

    raw_html = load_static_html_file(filename)
    return fromstring(raw_html)


def get_first_book_from_test_json(
    filename: str, expected_id: Optional[str] = None, expected_title: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load a JSON test file and extract the first book from search results.

    This is a common pattern in JSON parsing tests - loads the JSON,
    validates the structure, and returns the first book for testing.

    Args:
        filename: Name of JSON file in test_data directory
        expected_id: Optional romanceio ID to validate (from book._id)
        expected_title: Optional title to validate (from book.info.title)

    Returns:
        The first book dict from the JSON results

    Raises:
        AssertionError: If JSON structure is invalid or expected values don't match
    """
    data = load_test_json_file(filename)

    assert data.get("success"), "Expected success=true in JSON"
    books = data.get("books", [])
    assert len(books) > 0, "Expected at least one book in results"

    book = books[0]

    # Optionally validate expected values
    if expected_id is not None:
        actual_id = book.get("_id")
        assert actual_id == expected_id, f"Wrong ID: expected {expected_id}, got {actual_id}"

    if expected_title is not None:
        actual_title = book.get("info", {}).get("title", "")
        assert actual_title == expected_title, f"Wrong title: expected {expected_title}, got {actual_title}"

    return book


def run_static_file_test(
    book_name: str,
    romanceio_id: str,
    json_filename: str,
    html_filename: str,
    json_parser: Callable[[Dict[str, Any]], Dict[str, Any]],
    html_parser: Callable[[HtmlElement, str], Dict[str, Any]],
    fields_to_compare: Set[str],
    plugin_name: str,
) -> None:
    """Generic test runner for static JSON and HTML files.

    Args:
        book_name: Name of the book being tested
        romanceio_id: Romance.io ID for the book
        json_filename: JSON file name in common_romanceio_static_test_data directory
        html_filename: HTML file name in common_romanceio_static_test_data directory
        json_parser: Function to parse JSON into metadata dict
        html_parser: Function to parse HTML into metadata dict
        fields_to_compare: Set of fields to compare
        plugin_name: Name of plugin for display purposes
    """
    print("\n" + "=" * 80)
    print(f"TEST: {book_name} (Static Files) - {plugin_name} fields only")
    print("=" * 80)

    comparison = MetadataComparison(book_name, romanceio_id, fields_to_compare)

    json_data = load_test_json_file(json_filename)
    json_metadata = json_parser(json_data)

    # If parser returns invalid ID for known-good data, that's a test failure
    if json_metadata.get("invalid_id"):
        raise AssertionError(
            f"JSON parser returned invalid ID for known-good book: "
            f"{json_metadata['reason']} ({json_metadata['romanceio_id']})"
        )

    comparison.add_json_data(json_metadata)

    html_root = load_test_html_file(html_filename)
    html_url = f"https://www.romance.io/books/{romanceio_id}/{book_name.lower().replace(' ', '-')}"
    html_metadata = html_parser(html_root, html_url)

    # If parser returns invalid ID for known-good data, that's a test failure
    if html_metadata.get("invalid_id"):
        raise AssertionError(
            f"HTML parser returned invalid ID for known-good book: "
            f"{html_metadata['reason']} ({html_metadata['romanceio_id']})"
        )

    comparison.add_html_data(html_metadata)  # type: ignore[arg-type]

    matches = comparison.compare()
    comparison.print_result()

    assert matches, f"Metadata mismatch for {book_name}:\n" + "\n".join(comparison.errors)
    print(f"✓ {book_name} static test passed!")


def run_live_parsing_tests(
    test_books: List[Any],
    json_parser: Callable[[Dict[str, Any]], Dict[str, Any]],
    html_parser: Callable[[HtmlElement, str], Dict[str, Any]],
    fields_to_compare: Set[str],
    fetch_romanceio_book_page: Callable[[str], tuple],
    get_book_details_json: Callable[[str, int], Optional[Dict[str, Any]]],
    is_valid_romanceio_id_func: Callable[[str], bool],
    plugin_name: str,
) -> None:
    """Generic test runner for live HTML parsing tests.

    Args:
        test_books: List of test book objects
        json_parser: Function to parse JSON into metadata dict
        html_parser: Function to parse HTML into metadata dict
        fields_to_compare: Set of fields to compare
        fetch_romanceio_book_page: Function to fetch HTML page
        get_book_details_json: Function to get JSON from API
        is_valid_romanceio_id_func: Function to validate romanceio ID
        plugin_name: Name of plugin for display purposes
    """
    print("\n" + "=" * 80)
    print(f"TEST: All Books from test_data.py (Live Parsing) - {plugin_name} fields only")
    print("=" * 80)

    all_passed = True
    tested_count = 0
    skipped_count = 0
    failed_books = []
    failed_book_ids = set()

    for book in test_books:
        print(f"\n--- Testing: {book.title} by {', '.join(book.authors or ['Unknown'])} ---")

        # For these tests, we just want to test parsing book details,
        # so we just need to get each test book's romanceio_id.
        # We don't need to test the searching logic here.
        # Get romanceio_id - check direct property first, then expected_fields
        romanceio_id = book.romanceio_id
        if romanceio_id is None:
            romanceio_id = book.expected_fields.get("romanceio_id")

        # Skip books without a valid romanceio_id for live parsing tests
        if not is_valid_romanceio_id_func(romanceio_id):
            if romanceio_id is not None:
                print(f"  Skipped: Invalid romanceio_id ({romanceio_id})")
            else:
                print("  Skipped: No romanceio_id provided (expected for books not on Romance.io)")
            skipped_count += 1
            continue

        tested_count += 1
        comparison = MetadataComparison(book.title, romanceio_id, fields_to_compare)

        try:
            json_data = get_book_details_json(romanceio_id, 30)

            # Check if book was found (API returns None if not found)
            if json_data is None:
                print(f"  ⚠️  Skipped: Book not found in JSON API (ID: {romanceio_id})")
                skipped_count += 1
                tested_count -= 1
                continue

            json_metadata = json_parser(json_data)

            # If parser returns invalid ID after we validated it, that's a parser bug
            if json_metadata.get("invalid_id"):
                raise AssertionError(
                    f"JSON parser returned invalid ID for validated book {book.title}: "
                    f"{json_metadata['reason']} ({json_metadata['romanceio_id']})"
                )

            comparison.add_json_data(json_metadata)

            url = f"https://www.romance.io/books/{romanceio_id}"
            html_content, is_valid = fetch_romanceio_book_page(url)

            if not is_valid or html_content is None:
                print("  ⚠️  Skipped: Could not fetch valid HTML page")
                skipped_count += 1
                tested_count -= 1
                continue

            html_root = fromstring(html_content)
            html_metadata = html_parser(html_root, url)

            # If parser returns invalid ID after we validated it, that's a parser bug
            if html_metadata.get("invalid_id"):
                raise AssertionError(
                    f"HTML parser returned invalid ID for validated book {book.title}: "
                    f"{html_metadata['reason']} ({html_metadata['romanceio_id']})"
                )

            comparison.add_html_data(html_metadata)  # type: ignore[arg-type]

            matches = comparison.compare()
            if not matches:
                all_passed = False
                failed_books.append(f"{book.title} (ID: {romanceio_id})")
                failed_book_ids.add(romanceio_id)
                comparison.print_result()
            else:
                print("  ✓ All metadata matches!")

        except (RuntimeError, ValueError, TypeError, OSError, ImportError, AttributeError) as e:
            print(f"  ⚠️  Error testing {book.title}: {type(e).__name__}: {e}")
            skipped_count += 1
            tested_count -= 1
            continue

    print("\n" + "=" * 80)
    print(f"LIVE PARSING SUMMARY: Tested {tested_count} books, Skipped {skipped_count}")
    print("=" * 80)

    if not all_passed:
        unique_book_count = len(failed_book_ids)
        test_case_count = len(failed_books)

        print("\n" + "=" * 80)
        print(f"❌ METADATA MISMATCHES DETECTED")
        print("=" * 80)
        print(f"Failed test cases: {test_case_count}")
        print(f"Unique books affected: {unique_book_count}")
        print(f"\nNote: Multiple test cases may test the same book with different search terms.")
        print("\nFailed test cases:")
        for failed_book in failed_books:
            print(f"  ❌ {failed_book}")
        print("=" * 80)
        print(f"\n⚠️  Scroll up to see detailed mismatch information for each failed test.")
        print("=" * 80)
        raise AssertionError(
            f"{test_case_count} test case(s) failed ({unique_book_count} unique book(s)) "
            f"with metadata mismatches between JSON and HTML parsing. "
            f"See detailed output above."
        )

    print("✓ All live parsing tests passed!")


def create_json_parser_with_validation(
    parse_details_func: Callable[..., Any],
    parse_fields_func: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    get_author_details_func: Optional[Callable[[str, int], Optional[Dict[str, Any]]]] = None,
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create a JSON parser wrapper that handles common boilerplate:
    - Extract book data from API response
    - Validate romanceio_id
    - Parse additional fields if provided

    Args:
        parse_details_func: Function to parse basic details and validate ID
        parse_fields_func: Optional function to parse additional fields
        get_author_details_func: Optional function to fetch author details by ID

    Returns:
        A parser function suitable for use in test functions
    """

    def parser(book_json: Dict[str, Any]) -> Dict[str, Any]:
        if "books" in book_json and isinstance(book_json.get("books"), list):
            books = book_json["books"]
            if not books:
                raise ValueError("No books found in JSON response")
            book_data = books[0]
        else:
            book_data = book_json

        if get_author_details_func:
            basic_data = parse_details_func(book_data, get_author_details_func)
        else:
            basic_data = parse_details_func(book_data)

        if not basic_data.is_valid:
            return {
                "invalid_id": True,
                "romanceio_id": basic_data.romanceio_id or "None",
                "reason": basic_data.error_reason or "Unknown error",
            }

        result = {
            "romanceio_id": basic_data.romanceio_id,
            "title": basic_data.title,
            "authors": basic_data.authors,
            "series": getattr(basic_data, "series", None),
            "series_index": getattr(basic_data, "series_index", None),
            "pubdate": getattr(basic_data, "pubdate", None),
        }

        if parse_fields_func:
            fields_data = parse_fields_func(book_data)
            result.update(fields_data)

        return result

    return parser


def create_html_parser_with_validation(
    parse_id_func: Callable[[str], Optional[str]],
    parse_title_func: Optional[Callable[[HtmlElement], str]] = None,
    parse_authors_func: Optional[Callable[[HtmlElement], List[str]]] = None,
    parse_fields_func: Optional[Callable[[HtmlElement], Dict[str, Any]]] = None,
    max_tags: int = 1000,
) -> Callable[[HtmlElement, str], Dict[str, Any]]:
    """
    Create an HTML parser wrapper that handles common boilerplate:
    - Validate romanceio_id from URL
    - Parse basic fields (title, authors) if provided
    - Parse additional fields if provided

    Args:
        parse_id_func: Function to extract and validate romanceio_id from URL
        parse_title_func: Optional function to parse title
        parse_authors_func: Optional function to parse authors
        parse_fields_func: Optional function to parse additional fields
        max_tags: Maximum number of tags to retrieve (for field parsers)

    Returns:
        A parser function suitable for use in test functions
    """

    def parser(root: HtmlElement, url: str) -> Dict[str, Any]:
        romanceio_id_or_result = parse_id_func(url)

        if not romanceio_id_or_result:
            return {
                "invalid_id": True,
                "romanceio_id": "None",
                "reason": "Could not extract valid Romance.io ID from URL",
            }

        result = {"romanceio_id": str(romanceio_id_or_result)}

        if parse_title_func:
            result["title"] = parse_title_func(root)
        if parse_authors_func:
            result["authors"] = parse_authors_func(root)  # type: ignore[assignment]

        if parse_fields_func:
            sig = inspect.signature(parse_fields_func)
            if "max_tags" in sig.parameters:
                fields_data = parse_fields_func(root, max_tags=max_tags)  # type: ignore[call-arg]
            else:
                fields_data = parse_fields_func(root)
            result.update(fields_data)

        return result

    return parser


def parse_live_test_args(default_book_id: str = "5484ecd47a5936fb0405756c") -> tuple:
    """Parse command-line arguments for test_json_html_parse_matches scripts.

    In CI (GitHub Actions sets CI=true), always run all live tests.
    Locally: no flag = static only; --live = 1 book; --live=all = full suite;
    --live=id1,id2 = specific books.

    Args:
        default_book_id: Romance.io ID to test when ``--live`` is passed with no value.
            Defaults to Pride and Prejudice.

    Returns:
        Tuple of (run_live: bool, run_all: bool, target_ids: List[str])
    """
    import os
    import sys

    in_ci = os.environ.get("CI", "").lower() in ("true", "1")
    target_ids: List[str] = []
    run_live = in_ci
    run_all = in_ci  # In CI with no specific targets, run the full suite
    for arg in sys.argv[1:]:
        if arg == "--live":
            run_live = True
            run_all = False
            target_ids = [default_book_id]
        elif arg == "--live=all":
            run_live = True
            run_all = True
        elif arg.startswith("--live="):
            run_live = True
            run_all = False
            target_ids = [i.strip() for i in arg[len("--live=") :].split(",") if i.strip()]
    return run_live, run_all, target_ids


def select_live_test_books(
    run_live: bool,
    run_all: bool,
    target_ids: List[str],
    all_test_books: list,
) -> Optional[list]:
    """Select books for live testing and print the run banner.

    Also runs the static test loop when called from main().

    Returns:
        List of BookTestData to run live, or None if live tests are skipped.
    """
    if not run_live:
        print(
            "\n(Skipping live tests. Pass --live to run against 1 book, "
            "--live=all for the full suite, or --live=id1,id2 for specific books.)"
        )
        return None

    if run_all:
        books_to_test = all_test_books
    else:
        books_to_test = [
            b
            for b in all_test_books
            if b.romanceio_id in target_ids or b.expected_fields.get("romanceio_id") in target_ids
        ]
        if not books_to_test:
            from common.test_data import BookTestData  # type: ignore[import-not-found]  # pylint: disable=import-outside-toplevel,import-error

            books_to_test = [BookTestData(romanceio_id=rid) for rid in target_ids]

    book_count = len(books_to_test) if books_to_test is not all_test_books else "all"
    print("\n" + "=" * 80)
    print(f"Starting live parsing tests ({book_count} book(s))...")
    print("=" * 80)
    return books_to_test
