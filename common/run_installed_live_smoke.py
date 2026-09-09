"""Run one live access method using only production code from the installed ZIP."""

import argparse
import importlib
import os
import time
from unittest.mock import patch

from calibre.customize.ui import find_plugin

TEST_TITLE = "Pride and Prejudice"
TEST_AUTHORS = ["Jane Austen"]
EXPECTED_ROMANCEIO_ID = "5484ecd47a5936fb0405756c"
REQUEST_TIMEOUT_SECONDS = 10
MODULE_NAMES = (
    "common_romanceio_fetch_helper",
    "common_romanceio_json_api",
    "common_romanceio_search",
    "common_romanceio_search_orchestrator",
    "common_romanceio_transport",
    "fetch_helper",
    "parse_html",
    "parse_json",
)


def _log(message):
    print(message, flush=True)


def _load_installed_modules(plugin_path):
    modules = {}
    normalized_plugin_path = os.path.normcase(os.path.abspath(plugin_path))
    for child_name in MODULE_NAMES:
        module = importlib.import_module(f"calibre_plugins.romanceio_fields.{child_name}")
        module_file = getattr(module, "__file__", None)
        if not (module_file):
            raise AssertionError(f"Installed production module has no origin: {child_name}")
        normalized_module_path = os.path.normcase(os.path.abspath(module_file))
        if not (normalized_module_path.startswith(normalized_plugin_path)):
            raise AssertionError(f"{child_name} loaded from source instead of installed ZIP: {normalized_module_path}")
        modules[child_name] = module
    return modules


def _assert_fields(fields):
    if not (isinstance(fields, dict)):
        raise AssertionError(f"Expected parsed fields, got {type(fields).__name__}")
    if not (fields.get("star_rating") is not None):
        raise AssertionError("Missing star rating")
    if not (fields.get("rating_count") is not None):
        raise AssertionError("Missing rating count")
    tags = fields.get("tags")
    if not (isinstance(tags, list) and tags):
        raise AssertionError("Missing Romance.io tags")
    return fields


def _print_fields(fields):
    print(f"Steam rating: {fields.get('steam_rating')}")
    print(f"Star rating: {fields.get('star_rating')}")
    print(f"Rating count: {fields.get('rating_count')}")
    print(f"Tags: {len(fields.get('tags', []))}")


def _search_json(modules, title, authors, log_func, browser_fallback=False):
    json_api = modules["common_romanceio_json_api"]
    books = json_api.search_books_json(
        title,
        authors,
        timeout=REQUEST_TIMEOUT_SECONDS,
        log_func=log_func,
        browser_fetch_func=(
            (lambda url: modules["fetch_helper"].fetch_page(url, log_func=log_func)) if browser_fallback else None
        ),
    )
    return modules["common_romanceio_search"].find_best_json_match(books, title, authors, log_func)


def _search_embedded(modules, title, authors, log_func):
    def fetch_with_log(url, **kwargs):
        return modules["fetch_helper"].fetch_page(url, log_func=log_func, **kwargs)

    return modules["common_romanceio_search"].search_for_romanceio_id(
        title,
        authors,
        fetch_with_log,
        log_func=log_func,
    )


def _fetch_json_fields(modules, romanceio_id, log_func):
    book_json = modules["common_romanceio_json_api"].get_book_details_json(
        romanceio_id,
        timeout=REQUEST_TIMEOUT_SECONDS,
        log_func=log_func,
    )
    return modules["parse_json"].parse_fields_from_json(book_json) if book_json else None


def _fetch_ssr_fields(modules, romanceio_id, log_func):
    helper = modules["common_romanceio_fetch_helper"]
    raw_html, is_valid = helper.fetch_book_page_http(
        romanceio_id,
        log_func=log_func,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not raw_html or not is_valid:
        raise RuntimeError(f"Server-rendered book page was unavailable for {romanceio_id}")
    root = helper.parse_html_from_selenium(raw_html)
    return modules["parse_html"].parse_fields_from_ssr_html(root, max_tags=50)


def _fetch_embedded_fields(modules, romanceio_id, log_func):
    url = f"https://www.romance.io/books/{romanceio_id}"
    raw_html, is_valid = modules["fetch_helper"].fetch_romanceio_book_page(url, log=log_func)
    if not raw_html or not is_valid:
        raise RuntimeError(f"Browser book-page fetch was unavailable for {romanceio_id}")
    root = modules["common_romanceio_fetch_helper"].parse_html_from_selenium(raw_html)
    return modules["parse_html"].parse_fields_from_html(root, max_tags=50)


def run_method(method, modules):
    if method == "http-session":
        transport = modules["common_romanceio_transport"]

        @transport.lookup_budget
        def pooled(abort=None, log_func=_log):
            if not (abort is not None):
                raise AssertionError("Lookup budget was not initialized")
            if abort.is_set():
                raise AssertionError("Lookup was unexpectedly cancelled")
            found = _search_json(modules, TEST_TITLE, TEST_AUTHORS, log_func)
            if not (found == EXPECTED_ROMANCEIO_ID):
                raise AssertionError("Smoke check failed: found == EXPECTED_ROMANCEIO_ID")
            fields = _assert_fields(_fetch_ssr_fields(modules, found, log_func))
            _print_fields(fields)

        pooled()
        print("PASS: installed HTTP session completed search and full details without a browser")
        return
    if method in ("chrome-search", "chrome-details"):
        helper = modules["common_romanceio_fetch_helper"]
        real_fetch = helper._fetch_page_via_calibre_worker
        attempts = []

        def chrome_only(request, log, abort):
            # Force the production Chrome worker; Qt must not satisfy this check.
            attempts.append("chrome")
            if not (len(attempts) == 1):
                raise AssertionError("Chrome-only smoke unexpectedly retried")
            return real_fetch({**request, "backend": "chrome"}, log, abort)

        with patch.object(helper, "_fetch_page_via_calibre_worker", chrome_only):
            if method == "chrome-search":
                romanceio_id = _search_embedded(modules, TEST_TITLE, TEST_AUTHORS, _log)
                if not (romanceio_id == EXPECTED_ROMANCEIO_ID):
                    raise AssertionError(romanceio_id)
            else:
                _print_fields(_assert_fields(_fetch_embedded_fields(modules, EXPECTED_ROMANCEIO_ID, _log)))
        if not (attempts == ["chrome"]):
            raise AssertionError(attempts)
        print(f"PASS: installed Chrome-only production path completed: {method}")
        return
    if method == "json-clearance-reuse":
        messages = []

        def capture(message):
            messages.append(message)
            _log(message)

        first = _search_json(modules, TEST_TITLE, TEST_AUTHORS, capture, browser_fallback=True)
        if not (first == EXPECTED_ROMANCEIO_ID):
            raise AssertionError(first)
        time.sleep(6)
        # No browser callback: these calls must succeed using direct HTTP only.
        second = _search_json(modules, TEST_TITLE, TEST_AUTHORS, _log)
        if not (second == EXPECTED_ROMANCEIO_ID):
            raise AssertionError(second)
        time.sleep(6)
        _assert_fields(_fetch_ssr_fields(modules, EXPECTED_ROMANCEIO_ID, _log))
        if any("Saved temporary Cloudflare clearance" in message for message in messages):
            print("PASS: search and book details succeeded through direct HTTP after fresh clearance")
        else:
            print("PASS: direct HTTP search and details; fresh challenge clearance was not exercised on this run")
        return
    if method == "fields-job":
        from calibre.utils.ipc.simple_worker import fork_job

        result = fork_job(
            "calibre_plugins.romanceio_fields.jobs",
            "do_metadata_download",
            args=(
                [(1, EXPECTED_ROMANCEIO_ID, ["StarRating", "RomanceTags"], ["StarRating", "RomanceTags"], [])],
                50,
                1,
            ),
            timeout=180,
        )
        log_path = result["stdout_stderr"]
        if not (isinstance(log_path, str)):
            raise AssertionError("Calibre worker returned no log path")
        try:
            with open(log_path, encoding="utf-8", errors="replace") as stream:
                print(stream.read())
            book_results = result["result"]
            if not (isinstance(book_results, dict)):
                raise AssertionError(book_results)
            fields = book_results.get(1)
            if not (isinstance(fields, dict)):
                raise AssertionError(fields)
            if not (fields.get("StarRating")):
                raise AssertionError(fields)
            if not (fields.get("RomanceTags")):
                raise AssertionError(fields)
            if not (fields["__custom_fields_to_update__"] == ["StarRating", "RomanceTags"]):
                raise AssertionError(fields)
            print("PASS: installed Fields download job completed and returned ratings/tags")
        finally:
            try:
                os.remove(log_path)
            except OSError:
                pass
        return
    if method in ("json-search", "json-search-with-browser"):
        romanceio_id = _search_json(
            modules, TEST_TITLE, TEST_AUTHORS, _log, browser_fallback=method == "json-search-with-browser"
        )
        if not (romanceio_id == EXPECTED_ROMANCEIO_ID):
            raise AssertionError(f"Unexpected JSON search result: {romanceio_id!r}")
        print(f"PASS: JSON search resolved {romanceio_id}")
        return
    if method == "json-details":
        fields = _assert_fields(_fetch_json_fields(modules, EXPECTED_ROMANCEIO_ID, _log))
    elif method == "ssr-details":
        fields = _assert_fields(_fetch_ssr_fields(modules, EXPECTED_ROMANCEIO_ID, _log))
    elif method == "embedded-search":
        romanceio_id = _search_embedded(modules, TEST_TITLE, TEST_AUTHORS, _log)
        if not (romanceio_id == EXPECTED_ROMANCEIO_ID):
            raise AssertionError(f"Unexpected browser search result: {romanceio_id!r}")
        print(f"PASS: browser search (Qt first) resolved {romanceio_id}")
        return
    elif method == "embedded-details":
        fields = _assert_fields(_fetch_embedded_fields(modules, EXPECTED_ROMANCEIO_ID, _log))
    else:
        orchestrator = modules["common_romanceio_search_orchestrator"]
        romanceio_id = orchestrator.search_with_fallback(
            TEST_TITLE,
            TEST_AUTHORS,
            lambda title, authors, log: _search_json(modules, title, authors, log, browser_fallback=True),
            lambda title, authors, log: _search_embedded(modules, title, authors, log),
            log_func=_log,
            max_retries=1,
            retry_delay=0,
        )
        if not (romanceio_id == EXPECTED_ROMANCEIO_ID):
            raise AssertionError(f"Unexpected default search result: {romanceio_id!r}")
        fields = _assert_fields(
            orchestrator.fetch_details_with_fallback(
                romanceio_id,
                lambda book_id, log: _fetch_json_fields(modules, book_id, log),
                lambda book_id, log: _fetch_embedded_fields(modules, book_id, log),
                log_func=_log,
                max_retries=1,
                retry_delay=0,
                lightweight_html_fetch_func=lambda book_id, log: _fetch_ssr_fields(modules, book_id, log),
            )
        )
    _print_fields(fields)
    print(f"PASS: installed production path completed: {method}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "method",
        choices=(
            "http-session",
            "json-search",
            "json-search-with-browser",
            "json-clearance-reuse",
            "json-details",
            "ssr-details",
            "embedded-search",
            "embedded-details",
            "chrome-search",
            "chrome-details",
            "fields-job",
            "default",
        ),
    )
    args = parser.parse_args()

    plugin = find_plugin("Romance.io Fields")
    if not (plugin is not None):
        raise AssertionError("Romance.io Fields is not installed")
    plugin_path = os.path.abspath(plugin.plugin_path)
    print(f"Installed plugin ZIP: {plugin_path}")
    run_method(args.method, _load_installed_modules(plugin_path))


if __name__ == "__main__":
    main()
