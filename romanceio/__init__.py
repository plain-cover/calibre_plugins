"""
A Calibre plugin to add Romance.io as a source for book metadata.
"""

__license__ = "GPL v3"

import time
import re
import random

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote  # type: ignore[attr-defined,no-redef]  # Python 2 compatibility
try:
    from queue import Empty, Queue
except ImportError:
    from Queue import Empty, Queue  # type: ignore[import-not-found,no-redef]  # Python 2 compatibility

from typing import cast, List, Tuple
from six import text_type as unicode

from lxml.html import fromstring

from calibre import as_unicode
from calibre.ebooks import normalize
from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.sources.base import Source, fixcase, fixauthors
from calibre.utils.icu import lower
from calibre.utils.cleantext import clean_ascii_chars
from calibre.constants import numeric_version as calibre_version

# Plugin metadata constants - keep these in sync with the values in the RomanceIO class below
PLUGIN_NAME = "Romance.io"
PLUGIN_DESCRIPTION = "Downloads metadata from Romance.io"
PLUGIN_AUTHOR = "plain-cover"
PLUGIN_VERSION = (1, 0, 1)
PLUGIN_MINIMUM_CALIBRE_VERSION = (2, 0, 0)


class RomanceIO(Source):  # pylint: disable=abstract-method

    name = "Romance.io"  # Must match PLUGIN_NAME
    description = "Downloads metadata from Romance.io"  # Must match PLUGIN_DESCRIPTION
    author = "plain-cover"  # Must match PLUGIN_AUTHOR
    version = (1, 0, 1)  # Must match PLUGIN_VERSION
    minimum_calibre_version = (2, 0, 0)  # Must match PLUGIN_MINIMUM_CALIBRE_VERSION

    capabilities = frozenset(["identify", "cover"])
    touched_fields = frozenset(["title", "authors", "identifier:romanceio", "tags", "series", "pubdate"])
    has_html_comments = True
    supports_gzip_transfer_encoding = True

    ID_NAME = "romanceio"
    BASE_URL = "https://www.romance.io"

    @property
    def user_agent(self):
        # This utter filth is necessary to deal with periods of time when calibre did or did not have
        # various iterations of a random chrome user agent function.
        if cast(Tuple[int, int, int], calibre_version) >= (5, 40, 0):
            from calibre.utils.random_ua import random_common_chrome_user_agent

            return random_common_chrome_user_agent()
        if cast(Tuple[int, int, int], calibre_version) <= (5, 8, 1):
            from calibre.utils.random_ua import random_chrome_ua  # type: ignore[attr-defined]  # pylint: disable=no-name-in-module

            return random_chrome_ua()
        # From 5.9.0 to 5.39.1 there was no function, we will have to replicate the equivalent code here
        from calibre.utils.random_ua import (  # type: ignore[attr-defined]  # pylint: disable=no-name-in-module
            all_chrome_versions,  # type: ignore[attr-defined]
            random_desktop_platform,
        )

        chrome_version = random.choice(all_chrome_versions())
        render_chrome_version = (
            "Mozilla/5.0 ({p}) AppleWebKit/{wv} (KHTML, like Gecko) "
            "Chrome/{cv} Safari/{wv}".format(
                p=random_desktop_platform(),
                wv=chrome_version["webkit_version"],
                cv=chrome_version["chrome_version"],
            )
        )
        return render_chrome_version

    def config_widget(self):
        """
        Overriding the default configuration screen for our own custom configuration
        """
        from .config import ConfigWidget

        return ConfigWidget(self)

    def get_book_url(self, identifiers):
        """Return a user-friendly URL for the book on Romance.io."""
        romanceio_id = identifiers.get(self.ID_NAME, None)
        if romanceio_id:
            return (
                "romanceio",
                romanceio_id,
                f"{RomanceIO.BASE_URL}/books/{romanceio_id}",
            )
        return None

    def id_from_url(self, url):
        """Parse a URL and return a tuple of the form:
        (identifier_type, identifier_value).
        If the URL does not match the pattern for the metadata source,
        return None."""
        match = re.match(self.BASE_URL + r"/books/([a-f0-9]+).*", url)
        if match:
            return (self.ID_NAME, match.groups(0)[0])
        return None

    def create_query(self, _log, title=None, authors=None, identifiers=None, asin=None):
        """Construct a query URL to search for a book on Romance.io."""
        if identifiers is None:
            identifiers = {}

        isbn = check_isbn(identifiers.get("isbn", None))
        q = ""
        if isbn:
            q = "q=" + isbn
        elif asin:
            q = "q=" + asin
        elif title or authors:
            tokens = []
            title_tokens = list(self.get_title_tokens(title, strip_joiners=False, strip_subtitle=True))
            tokens += title_tokens
            author_tokens = self.get_author_tokens(authors, only_first_author=True)
            tokens += author_tokens
            tokens = [quote(t.encode("utf-8") if isinstance(t, unicode) else t) for t in tokens]
            q = "+".join(tokens)
            q = "q=" + q

        if not q:
            return None
        return RomanceIO.BASE_URL + "/search?" + q

    def get_cached_cover_url(self, identifiers):
        url = None
        romanceio_id = identifiers.get(self.ID_NAME, None)
        if romanceio_id is not None:
            url = self.cached_identifier_to_cover_url(romanceio_id)
        return url

    def clean_downloaded_metadata(self, mi):
        """
        Overridden from the calibre default so that we can stop this plugin messing
        with the tag casing coming from Romance.io.
        """
        docase = mi.language == "eng" or mi.is_null("language")
        if docase and mi.title:
            mi.title = fixcase(mi.title)

    def identify(
        self,
        log,
        result_queue,
        abort,
        title=None,
        authors=None,
        identifiers=None,
        timeout=30,  # pylint: disable=unused-argument
    ):
        """Identify a book by its Title/Author/etc."""
        if identifiers is None:
            identifiers = {}
        matches = []
        romanceio_id = identifiers.get(self.ID_NAME, None)
        log.debug(f"identify - start. title={title}, authors={authors}, identifiers={identifiers}")
        # Unlike the other metadata sources, if we have a Romance.io ID then we
        # do not need to fire a "search" at Romance.io. Instead we will be
        # able to go straight to the URL for that book.
        # Note: We only use romance.io IDs, not Goodreads or other identifiers

        br = self.browser

        if romanceio_id:
            matches.append(f"{RomanceIO.BASE_URL}/books/{romanceio_id}")
        else:
            # Can't find a valid id, so search using the title and authors.
            title = normalize(title)

            # Try JSON API search first, with fallback to HTML
            log.info("Searching for book...")
            try:
                from calibre_plugins.romanceio.common_romanceio_search_orchestrator import (  # type: ignore[import-not-found]  # pylint: disable=import-error
                    search_with_fallback,
                )

                def json_search(title, authors, log_func):
                    from calibre_plugins.romanceio.common_romanceio_json_api import search_books_json  # type: ignore[import-not-found]  # pylint: disable=import-error
                    from calibre_plugins.romanceio.common_romanceio_search import find_best_json_match  # type: ignore[import-not-found]  # pylint: disable=import-error

                    books = search_books_json(title, authors, 30, log_func)
                    if books and len(books) > 0:
                        return find_best_json_match(books, title, authors, log_func)
                    return None

                def html_search(title, authors, log_func):
                    from calibre_plugins.romanceio.common_romanceio_fetch_helper import fetch_page  # type: ignore[import-not-found]  # pylint: disable=import-error
                    from calibre_plugins.romanceio.common_romanceio_search import search_for_romanceio_id  # type: ignore[import-not-found]  # pylint: disable=import-error

                    return search_for_romanceio_id(title, authors, fetch_page, log_func)

                json_id = search_with_fallback(title, authors, json_search, html_search, log.info)
                if json_id:
                    matches.append(f"{RomanceIO.BASE_URL}/books/{json_id}")
                else:
                    log.info("Search completed but found no matching book")
            except (OSError, ValueError, RuntimeError) as e:
                log.exception(f"Search failed with error: {type(e).__name__}: {e}")

        if abort.is_set():
            return None

        if not matches:
            log.info("No matches found - cannot retrieve metadata")
            return None

        log.info(f"Found {len(matches)} match(es), fetching detailed metadata...")

        from .worker import Worker

        workers = [Worker(url, result_queue, br, log, i, self) for i, url in enumerate(matches)]

        for w in workers:
            w.start()
            # Don't send all requests at the same time
            time.sleep(1)

        while not abort.is_set():
            a_worker_is_alive = False
            for w in workers:
                w.join(0.2)
                if abort.is_set():
                    break
                if w.is_alive():
                    a_worker_is_alive = True
            if not a_worker_is_alive:
                break

        return None

    def parse_search_results(self, log, result_queue, orig_title, orig_authors, root, matches, _timeout):
        """Parse Romance.io search results and add matching book to result queue."""
        from calibre.ebooks.metadata.book.base import Metadata
        from calibre_plugins.romanceio.common_romanceio_search import (  # type: ignore[import-not-found]  # pylint: disable=import-error
            parse_search_results_for_id_and_cover,
        )

        log.info(f"parse_search_results - orig_title={orig_title}, orig_authors={orig_authors}")

        # Use shared parsing logic
        result = parse_search_results_for_id_and_cover(root, orig_title, orig_authors, log_func=log.info)

        if result:
            romanceio_id, title, authors, cover_url = result

            book_url = f"{RomanceIO.BASE_URL}/books/{romanceio_id}"
            matches.append(book_url)

            if cover_url:
                log.info(f"Caching cover URL for romanceio_id={romanceio_id}")
                self.cache_identifier_to_cover_url(romanceio_id, cover_url)

            mi = Metadata(title, authors)
            mi.set_identifier("romanceio", romanceio_id)
            mi.has_cover = bool(cover_url)
            result_queue.put(mi)
            log.info("Added metadata to result queue")
        else:
            log.info("No matching book found in search results")

    def download_cover(
        self,
        log,
        result_queue,
        abort,
        title=None,  # pylint: disable=unused-argument
        authors=None,  # pylint: disable=unused-argument
        identifiers=None,
        timeout=30,
        get_best_cover=False,  # pylint: disable=unused-argument
    ):
        if identifiers is None:
            identifiers = {}

        # Try to get from cache first
        cached_url = self.get_cached_cover_url(identifiers)

        # If not in cache, try to construct URL directly from romanceio_id
        if cached_url is None:
            romanceio_id = identifiers.get("romanceio", None)
            if romanceio_id:
                # Construct cover URL directly: https://s3.amazonaws.com/romance.io/books/large/{id}.jpg
                cached_url = f"https://s3.amazonaws.com/romance.io/books/large/{romanceio_id}.jpg"
            else:
                log.info("No cached cover URL found and no romanceio identifier")
                return

        if abort.is_set():
            return
        br = self.browser
        log("Downloading cover from:", cached_url)
        try:
            cdata = br.open_novisit(cached_url, timeout=timeout).read()
            result_queue.put((self, cdata))
        except (OSError, ValueError, RuntimeError):
            log.exception(f"Failed to download cover from: {cached_url}")

    def test_fields(self, mi):
        """
        Overridden because for our tests below we don't get all fields back for all books being tested
        and some fields are only populated conditionally based on user settings.
        """
        ignore_fields = ["identifier:romanceio", "series"]
        for key in self.touched_fields:
            if key not in ignore_fields:
                if key.startswith("identifier:"):
                    key = key.partition(":")[-1]
                    if not mi.has_identifier(key):
                        return "identifier: " + key
                elif mi.is_null(key):
                    return key
        return None


if __name__ == "__main__":
    # To run these tests use:
    # calibre-debug -e __init__.py
    import sys
    import os

    # Add parent directory to path to import shared test utilities
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from calibre.ebooks.metadata.sources.test import (
        test_identify_plugin,
        title_test,
        authors_test,
        series_test,
        pubdate_test,
    )

    from common.test_data import TEST_BOOKS, verify_and_print_plugin

    def get_test_stats(results):
        """Calculate passed/failed counts from results list."""
        count_passed = sum(results)
        count_failed = len(results) - count_passed
        return count_passed, count_failed

    def print_banner(char, text=""):
        """Print a formatted banner."""
        print(f"\n{char*80}")
        if text:
            print(text)
            print(char * 80)

    def print_test_result(test_num, test_passed, results, extra_info=""):
        """Print formatted test result with running totals."""
        passed_so_far, failed_so_far = get_test_stats(results)
        if test_passed:
            passed_so_far += 1
        else:
            failed_so_far += 1

        status = "✓" if test_passed else "❌"
        status_text = "PASSED" if test_passed else "FAILED"
        print_banner("*", f"{status} TEST {test_num} {status_text}")
        print(f"[{passed_so_far} passed / {failed_so_far} failed so far]")
        if extra_info:
            print(extra_info)
        print("*" * 80)

    def run_test_with_retry(test_func, max_retries=3):
        """Run a test with retry logic. Returns (success, needed_retry)."""
        for retry_attempt in range(1, max_retries + 1):
            if retry_attempt > 1:
                print(f"  > Retry attempt {retry_attempt}/{max_retries}")

            try:
                test_func()
                return True, retry_attempt > 1
            except (AssertionError, SystemExit):
                if retry_attempt < max_retries:
                    print(f"\n  ✗ Test failed on attempt {retry_attempt}, retrying after 2s...")
                    time.sleep(2)
                else:
                    return False, False
            except Exception:  # pylint: disable=broad-except
                return False, False
        return False, False

    # ===== Metadata verification tests =====
    print("=" * 80)
    print("Running metadata verification tests...")
    print("=" * 80)

    # Verify plugin can be instantiated and metadata is correct
    plugin_path = os.path.abspath(__file__)
    plugin = verify_and_print_plugin(
        RomanceIO,
        plugin_path,
        PLUGIN_NAME,
        PLUGIN_VERSION,
        PLUGIN_AUTHOR,
        PLUGIN_MINIMUM_CALIBRE_VERSION,
        additional_info={"Capabilities": ", ".join(["identify", "cover"])},
    )

    assert "identify" in plugin.capabilities, "Expected 'identify' capability"
    assert "cover" in plugin.capabilities, "Expected 'cover' capability"
    print()

    # ===== Functional tests =====
    print("=" * 80)
    print("Running functional tests...")
    print("=" * 80)

    test_cases = []
    negative_test_cases = []

    for book in TEST_BOOKS:
        query = {
            k: v
            for k, v in [
                (
                    "identifiers",
                    {"romanceio": book.romanceio_id} if book.romanceio_id else None,
                ),
                ("title", book.title),
                ("authors", book.authors),
            ]
            if v is not None
        }

        expected_romanceio_id = book.expected_fields.get("romanceio_id")

        if expected_romanceio_id is None:
            negative_test_cases.append((query, book))
            continue

        expected_title = book.expected_fields.get("title", book.title)
        expected_authors = book.expected_fields.get("authors", book.authors)

        expected = [
            title_test(expected_title, exact=True),
            authors_test(expected_authors),
        ]

        if "series" in book.expected_fields:
            expected_series = book.expected_fields["series"]
            if expected_series is not None:
                expected.append(series_test(expected_series, book.expected_fields.get("series_index")))

        if "pubdate" in book.expected_fields:
            expected_pubdate = book.expected_fields["pubdate"]
            if expected_pubdate is not None:
                expected.append(pubdate_test(*cast(Tuple[int, int, int], expected_pubdate)))

        test_cases.append((query, expected))

    if test_cases:
        print_banner("=", f"Running {len(test_cases)} positive tests")

        MAX_RETRIES = 3
        test_results: List[bool] = []
        RETRY_COUNT = 0

        for i, (query, expected) in enumerate(test_cases):
            BOOK_INFO = f"Book {i+1}/{len(test_cases)}"
            if "title" in query:
                BOOK_INFO += f": '{query['title']}'"
            if "authors" in query:
                BOOK_INFO += f" by {query['authors']}"

            print(f"\n{'-'*80}")
            print(f"TEST {i+1}/{len(test_cases)}: {BOOK_INFO}")
            print(f"{'-'*80}")

            def run_test(q=query, exp=expected):
                test_identify_plugin(RomanceIO.name, [(q, exp)])

            success, needed_retry = run_test_with_retry(run_test, max_retries=MAX_RETRIES)
            test_results.append(success)
            if needed_retry:
                RETRY_COUNT += 1
            print_test_result(i + 1, success, test_results[:-1], "" if success else "Error in test")

        passed, failed = get_test_stats(test_results)
        TOTAL = len(test_results)
        SUMMARY = f"POSITIVE TEST SUMMARY: {passed}/{TOTAL} PASSED, {failed}/{TOTAL} FAILED"
        print_banner("=", SUMMARY)
        if RETRY_COUNT > 0:
            print(f"Note: {RETRY_COUNT} test(s) required retries to pass")
            print("=" * 80)
        if failed > 0:
            print(f"⚠ WARNING: {failed} test(s) failed after {MAX_RETRIES} retries each")

    if negative_test_cases:
        print_banner("=", f"Running {len(negative_test_cases)} negative test(s) (expecting no results)")

        MAX_RETRIES = 3
        negative_test_results: List[bool] = []  # type: ignore[misc]
        NEGATIVE_RETRY_COUNT = 0

        for i, (query, book) in enumerate(negative_test_cases):
            print(f"\n{'-'*80}")
            print(f"NEGATIVE TEST {i+1}/{len(negative_test_cases)}: '{book.title}' by {book.authors}")
            print(f"{'-'*80}")

            def run_negative_test(q=query):
                test_identify_plugin(RomanceIO.name, [(q, [])])
                raise AssertionError("Expected no match but found results")

            SUCCESS = False
            for attempt in range(1, MAX_RETRIES + 1):
                if attempt > 1:
                    print(f"  > Retry attempt {attempt}/{MAX_RETRIES}")

                try:
                    run_negative_test()
                    if attempt < MAX_RETRIES:
                        print(f"\n  ✗ Expected no match but found results on attempt {attempt}, retrying after 2s...")
                        time.sleep(2)
                    else:
                        SUCCESS = False
                        break
                except (SystemExit, AssertionError) as e:
                    ERROR_MSG = str(e)
                    if isinstance(e, SystemExit) or "No results" in ERROR_MSG or "no results" in ERROR_MSG.lower():
                        SUCCESS = True
                        if attempt > 1:
                            NEGATIVE_RETRY_COUNT += 1
                        break
                    if attempt < MAX_RETRIES:
                        print(f"\n  ✗ Unexpected error on attempt {attempt}, retrying after 2s...")
                        time.sleep(2)
                    else:
                        SUCCESS = False
                        break
                except Exception:  # pylint: disable=broad-except
                    SUCCESS = False
                    break

            negative_test_results.append(SUCCESS)
            EXTRA_MSG = "Correctly found no match" if SUCCESS else "Expected no match but found results (or error)"
            print_test_result(i + 1, SUCCESS, negative_test_results[:-1], EXTRA_MSG)

        num_passed, num_failed = get_test_stats(negative_test_results)
        TOTAL = len(negative_test_results)
        SUMMARY = f"NEGATIVE TEST SUMMARY: {num_passed}/{TOTAL} PASSED, {num_failed}/{TOTAL} FAILED"
        print_banner("=", SUMMARY)
        if NEGATIVE_RETRY_COUNT > 0:
            print(f"Note: {NEGATIVE_RETRY_COUNT} test(s) required retries to pass")
            print("=" * 80)
        if num_failed > 0:
            print(f"⚠ ERROR: {num_failed} negative test(s) failed after {MAX_RETRIES} retries each")

    if not test_cases and not negative_test_cases:
        print("No test cases to run")

    TOTAL_FAILURES = (len(test_results) - sum(test_results) if test_cases else 0) + (
        len(negative_test_results) - sum(negative_test_results) if negative_test_cases else 0
    )

    if TOTAL_FAILURES > 0:
        print(f"\n{'='*80}")
        print(f"❌ TEST SUITE FAILED: {TOTAL_FAILURES} test(s) failed")
        print(f"{'='*80}")
        sys.exit(1)
    else:
        print(f"\n{'='*80}")
        print("✅ ALL TESTS PASSED")
        print(f"{'='*80}")
        sys.exit(0)
