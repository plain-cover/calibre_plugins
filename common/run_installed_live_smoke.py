"""Run one live access method using only production code from the installed ZIP."""

import argparse
import importlib
import os

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
        assert module_file, f"Installed production module has no origin: {child_name}"
        normalized_module_path = os.path.normcase(os.path.abspath(module_file))
        assert normalized_module_path.startswith(
            normalized_plugin_path
        ), f"{child_name} loaded from source instead of installed ZIP: {normalized_module_path}"
        modules[child_name] = module
    return modules


def _assert_fields(fields):
    assert isinstance(fields, dict), f"Expected parsed fields, got {type(fields).__name__}"
    assert fields.get("star_rating") is not None, "Missing star rating"
    assert fields.get("rating_count") is not None, "Missing rating count"
    tags = fields.get("tags")
    assert isinstance(tags, list) and tags, "Missing Romance.io tags"
    return fields


def _print_fields(fields):
    print(f"Steam rating: {fields.get('steam_rating')}")
    print(f"Star rating: {fields.get('star_rating')}")
    print(f"Rating count: {fields.get('rating_count')}")
    print(f"Tags: {len(fields.get('tags', []))}")


def _search_json(modules, title, authors, log_func):
    json_api = modules["common_romanceio_json_api"]
    books = json_api.search_books_json(
        title,
        authors,
        timeout=REQUEST_TIMEOUT_SECONDS,
        log_func=log_func,
    )
    return modules["common_romanceio_search"].find_best_json_match(books, title, authors, log_func)


def _search_chrome(modules, title, authors, log_func):
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


def _fetch_chrome_fields(modules, romanceio_id, log_func):
    url = f"https://www.romance.io/books/{romanceio_id}"
    raw_html, is_valid = modules["fetch_helper"].fetch_romanceio_book_page(url, log=log_func)
    if not raw_html or not is_valid:
        raise RuntimeError(f"Chrome book-page fetch was unavailable for {romanceio_id}")
    root = modules["common_romanceio_fetch_helper"].parse_html_from_selenium(raw_html)
    return modules["parse_html"].parse_fields_from_html(root, max_tags=50)


def run_method(method, modules):
    if method == "json-search":
        romanceio_id = _search_json(modules, TEST_TITLE, TEST_AUTHORS, _log)
        assert romanceio_id == EXPECTED_ROMANCEIO_ID, f"Unexpected JSON search result: {romanceio_id!r}"
        print(f"PASS: JSON search resolved {romanceio_id}")
        return
    if method == "json-details":
        fields = _assert_fields(_fetch_json_fields(modules, EXPECTED_ROMANCEIO_ID, _log))
    elif method == "ssr-details":
        fields = _assert_fields(_fetch_ssr_fields(modules, EXPECTED_ROMANCEIO_ID, _log))
    elif method == "chrome-search":
        romanceio_id = _search_chrome(modules, TEST_TITLE, TEST_AUTHORS, _log)
        assert romanceio_id == EXPECTED_ROMANCEIO_ID, f"Unexpected Chrome search result: {romanceio_id!r}"
        print(f"PASS: Chrome search resolved {romanceio_id}")
        return
    elif method == "chrome-details":
        fields = _assert_fields(_fetch_chrome_fields(modules, EXPECTED_ROMANCEIO_ID, _log))
    else:
        orchestrator = modules["common_romanceio_search_orchestrator"]
        romanceio_id = orchestrator.search_with_fallback(
            TEST_TITLE,
            TEST_AUTHORS,
            lambda title, authors, log: _search_json(modules, title, authors, log),
            lambda title, authors, log: _search_chrome(modules, title, authors, log),
            log_func=_log,
            max_retries=1,
            retry_delay=0,
        )
        assert romanceio_id == EXPECTED_ROMANCEIO_ID, f"Unexpected default search result: {romanceio_id!r}"
        fields = _assert_fields(
            orchestrator.fetch_details_with_fallback(
                romanceio_id,
                lambda book_id, log: _fetch_json_fields(modules, book_id, log),
                lambda book_id, log: _fetch_chrome_fields(modules, book_id, log),
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
        choices=("json-search", "json-details", "ssr-details", "chrome-search", "chrome-details", "default"),
    )
    args = parser.parse_args()

    plugin = find_plugin("Romance.io Fields")
    assert plugin is not None, "Romance.io Fields is not installed"
    plugin_path = os.path.abspath(plugin.plugin_path)
    print(f"Installed plugin ZIP: {plugin_path}")
    run_method(args.method, _load_installed_modules(plugin_path))


if __name__ == "__main__":
    main()
