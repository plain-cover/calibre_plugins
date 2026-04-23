#!/usr/bin/env python3
"""
Update static test data files from Romance.io.

This script downloads fresh JSON and HTML files for books by their romanceio_id.
Run this manually when you need to refresh test data to match current site format.

⚠️  IMPORTANT: Search HTML requires browser automation (SeleniumBase).
    Run from romanceio/ directory AFTER building:
    cd ../romanceio && calibre-debug ../common/update_static_test_data.py --all

Usage:
    calibre-debug update_static_test_data.py [--update ROMANCEIO_ID | --add ROMANCEIO_ID | --all]

Options:
    --update ROMANCEIO_ID  Update an existing book by its romanceio_id
    --add ROMANCEIO_ID     Add a new book by downloading files for the given romanceio_id
                           (You'll still need to manually add it to STATIC_TEST_BOOKS)
    --all                  Update all books in STATIC_TEST_BOOKS

Examples:
    # Update all books (run from romanceio/ directory after ./build.sh)
    cd romanceio && calibre-debug ../common/update_static_test_data.py --all

    # Update a specific book by ID
    calibre-debug update_static_test_data.py --update 5484ecd47a5936fb0405756c

    # Add a new book by ID
    calibre-debug update_static_test_data.py --add 65b604fa00d361e53f20ecfb
"""

import argparse
import json
import os
import sys
import time
import traceback

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common_romanceio_static_test_data import STATIC_TEST_BOOKS, StaticTestBook  # pylint: disable=import-error

from common_romanceio_json_api import (  # pylint: disable=import-error
    get_book_details_json,
    get_author_details_json,
)

try:
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen  # type: ignore[import-not-found,no-redef]


def download_book_json(book: StaticTestBook, output_dir: str) -> bool:
    """Download book details JSON."""
    print(f"  Downloading book JSON for {book.romanceio_id}...")
    try:
        book_json = get_book_details_json(book.romanceio_id, timeout=30, log_func=print)
        if not book_json:
            print(f"    ⚠️  No book data returned for {book.romanceio_id}")
            return False

        output_path = os.path.join(output_dir, book.json_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(book_json, f, indent=2, ensure_ascii=False)

        print(f"    ✓ Saved to {book.json_filename}")
        return True
    except Exception as e:  # pylint: disable=broad-except
        print(f"    ❌ Failed: {e}")
        return False


def download_book_html(book: StaticTestBook, output_dir: str) -> bool:
    """Download book details HTML page."""
    print(f"  Downloading book HTML for {book.romanceio_id}...")

    url = f"https://www.romance.io/books/{book.romanceio_id}"

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        request = Request(url, headers=headers)

        with urlopen(request, timeout=30) as response:
            html_content = response.read()

        output_path = os.path.join(output_dir, book.html_filename)
        with open(output_path, "wb") as f:
            f.write(html_content)

        print(f"    ✓ Saved to {book.html_filename} ({len(html_content)} bytes)")
        return True
    except Exception as e:  # pylint: disable=broad-except
        print(f"    ❌ Failed: {e}")
        print(f"    URL: {url}")
        return False


def download_search_json(book: StaticTestBook, output_dir: str) -> bool:
    """Download search results JSON using the exact same function as the plugin."""
    if not book.search_json_filename:
        print("  Skipping search JSON (not configured)")
        return True

    print(f"  Downloading search JSON for '{book.title}'...")

    try:
        # Import from plugin namespace (requires running from plugin directory)
        try:
            # type: ignore[import-not-found] # noqa: E501
            from calibre_plugins.romanceio.common_romanceio_json_api import search_books_json
        except ImportError:
            # Fallback to common import (may fail due to relative imports)
            print("    ❌ Failed: Cannot import from plugin namespace")
            print("    💡 Run from romanceio/ directory after ./build.sh:")
            print("       cd romanceio && calibre-debug ../common/update_static_test_data.py --all")
            return False

        # Use the exact same function as the romanceio plugin
        books = search_books_json(book.title, book.authors, timeout=30, log_func=print)

        # Reconstruct the response format that includes the success flag
        search_results = {"success": True, "books": books}

        output_path = os.path.join(output_dir, book.search_json_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(search_results, f, indent=2, ensure_ascii=False)

        print(f"    ✓ Saved to {book.search_json_filename} ({len(books)} results)")
        return True
    except Exception as e:  # pylint: disable=broad-except
        print(f"    ❌ Failed: {e}")
        return False


def download_search_html(book: StaticTestBook, output_dir: str) -> bool:
    """Download search results HTML using the exact same functions as the plugin.

    Requires SeleniumBase - run from romanceio/ directory after building the plugin.
    Uses the exact same search flow as the romanceio plugin's identify() method.
    """
    if not book.search_html_filename:
        print("  Skipping search HTML (not configured)")
        return True

    print(f"  Downloading search HTML for '{book.title}' (using browser for JavaScript)...")

    try:
        # Import from plugin namespace (requires running from plugin directory)
        try:
            # type: ignore[import-not-found] # noqa: E501
            from calibre_plugins.romanceio.common_romanceio_fetch_helper import fetch_page

            # type: ignore[import-not-found] # noqa: E501
            from calibre_plugins.romanceio.common_romanceio_search import search_for_romanceio_id
        except ImportError:
            # Fallback to common import (won't have SeleniumBase dependencies)
            print("    ❌ Failed: Cannot import from plugin namespace")
            print("    💡 Run from romanceio/ directory after ./build.sh:")
            print("       cd romanceio && calibre-debug ../common/update_static_test_data.py --all")
            return False

        # Create a wrapper for fetch_page that matches the expected signature
        def fetch_page_func(
            url, wait_for_element=None, not_found_marker=None, secondary_wait_element=None, max_wait=30
        ):
            return fetch_page(
                url,
                plugin_name="romanceio",
                wait_for_element=wait_for_element,
                not_found_marker=not_found_marker,
                secondary_wait_element=secondary_wait_element,
                max_wait=max_wait,
            )

        # Use the exact same search function as the plugin to get HTML
        # This ensures we're fetching and parsing exactly as the plugin does
        # The function will raise RuntimeError if fetch fails, return None if no match
        romanceio_id = search_for_romanceio_id(book.title, book.authors, fetch_page_func, log_func=print)

        # Even if no match found, we still have the HTML from the fetch
        # Re-fetch to save the raw HTML (the above call was for testing the search logic)
        # type: ignore[import-not-found] # pylint: disable=import-error
        from calibre_plugins.romanceio.common_romanceio_search import _build_search_query

        url = _build_search_query(book.title, book.authors)
        if not url:
            print("    ❌ Failed to build search URL")
            return False

        print(f"    Fetching HTML from: {url}")
        html_content = fetch_page(
            url,
            plugin_name="romanceio",
            wait_for_element="book-results",
            secondary_wait_element="has-background",
            max_wait=30,
        )

        if not html_content or len(html_content) == 0:
            print("    ❌ Failed: Empty HTML content returned")
            return False

        output_path = os.path.join(output_dir, book.search_html_filename)
        with open(output_path, "wb") as f:
            # fetch_page returns a string - encode it to bytes for binary write
            f.write(html_content.encode("utf-8"))

        print(f"    ✓ Saved to {book.search_html_filename} ({len(html_content)} bytes)")
        if romanceio_id:
            print(f"    ✓ Verified search found book: {romanceio_id}")
        else:
            print("    ⚠️  Search did not find book (HTML saved but may need review)")
        return True
    except Exception as e:  # pylint: disable=broad-except
        print(f"    ❌ Failed: {e}")
        traceback.print_exc()
        return False


def download_author_json(book: StaticTestBook, output_dir: str) -> bool:
    """Download author details JSON for all authors."""
    print("  Downloading author JSON...")
    results = []

    for author_name, author_id in book.author_ids.items():
        print(f"    Downloading {author_name} ({author_id})...")
        try:
            author_json = get_author_details_json(author_id, timeout=30, log_func=print)
            if not author_json:
                print(f"      ⚠️  No author data returned for {author_id}")
                results.append(False)
                continue

            # Create filename from author ID
            filename = f"author_{author_id}.json"
            output_path = os.path.join(output_dir, filename)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(author_json, f, indent=2, ensure_ascii=False)

            print(f"      ✓ Saved to {filename}")
            results.append(True)
        except Exception as e:  # pylint: disable=broad-except
            print(f"      ❌ Failed: {e}")
            results.append(False)

    return all(results) if results else True


def update_book(book: StaticTestBook, output_dir: str) -> bool:
    """Update all files for a single book."""
    print(f"\nUpdating: {book.name}")
    print(f"  Romance.io ID: {book.romanceio_id}")

    results = []

    # Download book details (JSON and HTML)
    results.append(download_book_json(book, output_dir))
    time.sleep(1)

    results.append(download_book_html(book, output_dir))
    time.sleep(1)

    # Download search results (optional)
    if book.search_json_filename:
        results.append(download_search_json(book, output_dir))
        time.sleep(1)

    if book.search_html_filename:
        results.append(download_search_html(book, output_dir))
        time.sleep(1)

    # Download author data
    results.append(download_author_json(book, output_dir))

    success = all(results)
    status = "✓ Complete" if success else "⚠️  Completed with some failures"
    print(f"  {status}")

    return success


def add_new_book(romanceio_id: str, output_dir: str) -> bool:
    """Add a new book by downloading files for the given romanceio_id."""
    print(f"\nAdding new book with ID: {romanceio_id}")

    # First, fetch book details to get title and author info
    print("  Fetching book details to determine title and authors...")
    try:
        book_json = get_book_details_json(romanceio_id, timeout=30, log_func=print)
        if not book_json:
            print("  ❌ Failed to fetch book details. Check that the ID is valid.")
            return False

        # Extract book info
        info = book_json.get("info", {})
        title = info.get("title", "unknown_book")
        authors = info.get("authors", [])

        print(f"  Found: {title}")
        if authors:
            print(f"  Authors: {', '.join([a.get('name', '') for a in authors])}")

        # Create a temporary StaticTestBook object
        author_names = [a.get("name", "Unknown") for a in authors]
        author_ids = {a.get("name", "Unknown"): a.get("_id", "") for a in authors}

        temp_book = StaticTestBook(
            name=title,
            romanceio_id=romanceio_id,
            title=title,
            authors=author_names,
            author_ids=author_ids,
        )

        # Download all files using existing functions
        success = update_book(temp_book, output_dir)

        if success:
            print("\n" + "=" * 80)
            print("✓ Files downloaded successfully!")
            print("\nNext steps:")
            print("1. Add this entry to STATIC_TEST_BOOKS in common_romanceio_static_test_data.py:")
            print("\n    StaticTestBook(")
            print(f'        name="{title}",')
            print(f'        romanceio_id="{romanceio_id}",')
            print(f'        title="{title}",')
            print(f"        authors={author_names},")
            print(f"        author_ids={author_ids},")
            print("        star_rating=None,  # Fill in after checking the data")
            print("        steam_rating=None,  # Fill in after checking the data")
            print("        rating_count=None,  # Fill in after checking the data")
            print("        expected_tag_count=None,  # Fill in after checking the data")
            print("        sample_tags=[],  # Fill in after checking the data")
            print("    ),")
            print("\n2. Review the downloaded files in common_romanceio_static_test_data/")
            print("3. Fill in the expected values (star_rating, steam_rating, etc.)")
            print("4. Rebuild plugins and run tests")
            print("=" * 80)

        return success

    except Exception as e:  # pylint: disable=broad-except
        print(f"  ❌ Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Update static test data from Romance.io",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--update",
        type=str,
        metavar="ROMANCEIO_ID",
        help="Update an existing book by its romanceio_id",
    )
    parser.add_argument(
        "--add",
        type=str,
        metavar="ROMANCEIO_ID",
        help="Add a new book by downloading files for the given romanceio_id",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Update all books in STATIC_TEST_BOOKS",
    )

    args = parser.parse_args()

    options_count = sum([bool(args.update), bool(args.add), args.all])
    if options_count > 1:
        print("Error: Can only specify one of --update, --add, or --all")
        return 1
    if options_count == 0:
        print("Error: Must specify --update, --add, or --all")
        parser.print_help()
        return 1

    output_dir = os.path.join(script_dir, "common_romanceio_static_test_data")
    if not os.path.exists(output_dir):
        print(f"Error: Output directory not found: {output_dir}")
        return 1

    print("=" * 80)
    print("Romance.io Static Test Data Updater")
    print("=" * 80)
    print(f"Output directory: {output_dir}")

    if args.add:
        return 0 if add_new_book(args.add, output_dir) else 1

    if args.update:
        # Find the book in STATIC_TEST_BOOKS by ID
        matching_books = [b for b in STATIC_TEST_BOOKS if b.romanceio_id == args.update]
        if not matching_books:
            print(f"\nError: Book with ID '{args.update}' not found in STATIC_TEST_BOOKS")
            print("\nAvailable books:")
            for book in STATIC_TEST_BOOKS:
                print(f"  - {book.name} ({book.romanceio_id})")
            return 1

        book = matching_books[0]
        print(f"\nUpdating: {book.name}")
        success = update_book(book, output_dir)

        if success:
            print("\n✓ Update complete!")
            print("\nNext steps:")
            print("1. Review changes: git diff common/common_romanceio_static_test_data/")
            print("2. Rebuild plugins: cd romanceio && ./build.sh && cd ../romanceio_fields && ./build.sh")
            print("3. Run tests: calibre-debug test_json_html_parse_matches.py")
            print("4. Commit if tests pass")

        return 0 if success else 1

    if args.all:
        print(f"\nUpdating {len(STATIC_TEST_BOOKS)} books")

        results = []
        for book in STATIC_TEST_BOOKS:
            try:
                results.append(update_book(book, output_dir))
            except KeyboardInterrupt:
                print("\n\nInterrupted by user")
                return 1
            except Exception as e:  # pylint: disable=broad-except
                print(f"\n❌ Unexpected error updating {book.name}: {e}")
                results.append(False)

        print("\n" + "=" * 80)
        successful = sum(results)
        total = len(results)
        print(f"Summary: {successful}/{total} books updated successfully")

        if successful < total:
            print("\n⚠️  Some updates failed. Review the output above for details.")
            print("After fixing any issues, run this script again.")
        else:
            print("\n✓ All updates completed successfully!")
            print("\nNext steps:")
            print("1. Review the changes: git diff common/common_romanceio_static_test_data/")
            print("2. Rebuild both plugins: cd romanceio && ./build.sh && cd ../romanceio_fields && ./build.sh")
            print("3. Run tests to verify: calibre-debug test_json_html_parse_matches.py")
            print("4. Commit the changes if tests pass")

        print("=" * 80)
        return 0 if successful == total else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
