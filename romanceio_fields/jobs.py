"""
Jobs are tasks that run in a separate process.
We use jobs to manage downloading fields from Romance.io.
"""

import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


from calibre.customize.ui import quick_metadata
from calibre.ebooks import DRMError
from calibre.utils.ipc.server import Server
from calibre.utils.ipc.job import ParallelJob

from . import config as cfg


@dataclass
class _SsrParsedFields:
    """Wrapper returned by _fetch_html_lightweight to distinguish pre-parsed SSR fields
    from a raw JSON API dict. Avoids sentinel key pollution in the result dict."""

    fields: Dict[str, Any]


_JSON_REQUEST_TIMEOUT_SECS: int = 10
INTERNAL_CUSTOM_FIELDS_TO_UPDATE = "__custom_fields_to_update__"
INTERNAL_TAG_FIELDS_TO_UPDATE = "__tag_fields_to_update__"


def prepare_books_for_download(
    book_ids: List[int],
    fields_to_cols_map: Dict[str, str],
    rating_tag_fields: List[str],
    overwrite_existing: bool,
    db_path: str,
    notification: Callable[[float, str], float] = (lambda x, y: x),
) -> Tuple[List[Tuple], Dict[int, str], Dict[int, str], Dict[int, str]]:
    """
    Prepare books for downloading by searching for Romance.io IDs if needed.
    Returns (books_to_scan_raw, warnings, errors, saved_identifiers) where:
    - books_to_scan_raw: List of tuples containing the fields to fetch and the
      custom-column/rating-tag destinations to update
    - warnings: Dict of book_id -> warning message
    - errors: Dict of book_id -> error message
    - saved_identifiers: Dict of book_id -> romanceio_id (newly found IDs that were saved)
    """
    from calibre.library import db as calibre_db
    from calibre_plugins.romanceio_fields.common_romanceio_search_orchestrator import (  # type: ignore[import-not-found]  # pylint: disable=import-error
        search_with_fallback,
    )

    # Open database connection (old API)
    db = calibre_db(db_path)

    books_to_scan = []
    warnings = {}
    errors = {}
    saved_identifiers = {}
    total = len(book_ids)

    labels_map = dict(
        (col_name, db.field_metadata.key_to_label(col_name)) for col_name in fields_to_cols_map.values() if col_name
    )
    from calibre_plugins.romanceio_fields.rating_tags import (  # type: ignore[import-not-found]  # pylint: disable=import-error
        build_field_update_plan,
    )

    def json_search(title, authors, log_func):
        from calibre_plugins.romanceio_fields.common_romanceio_json_api import search_books_json  # type: ignore[import-not-found]  # pylint: disable=import-error
        from calibre_plugins.romanceio_fields.common_romanceio_search import find_best_json_match  # type: ignore[import-not-found]  # pylint: disable=import-error

        books = search_books_json(title, authors, _JSON_REQUEST_TIMEOUT_SECS, log_func)
        if books and len(books) > 0:
            return find_best_json_match(books, title, authors, log_func)
        return None

    def html_search(title, authors, log_func):
        from calibre_plugins.romanceio_fields.common_romanceio_search import search_for_romanceio_id  # type: ignore[import-not-found]  # pylint: disable=import-error
        from calibre_plugins.romanceio_fields.fetch_helper import fetch_page  # type: ignore[import-not-found]  # pylint: disable=import-error

        def fetch_with_log(url, **kwargs):
            return fetch_page(url, log_func=log_func, **kwargs)

        return search_for_romanceio_id(title, authors, fetch_with_log, log_func)

    for i, book_id in enumerate(book_ids):
        notification(float(i) / total, f"Finding book {i + 1} of {total}")

        try:
            # Check which fields need to be downloaded
            existing_custom_values = {}
            existing_tags = (
                db.tags(book_id, index_is_id=True) if rating_tag_fields else None  # type: ignore[attr-defined]
            )
            for field, col_name in fields_to_cols_map.items():
                if col_name:
                    lbl = labels_map[col_name]
                    existing_custom_values[field] = db.get_custom(book_id, label=lbl, index_is_id=True)

            fields_to_run, custom_fields_to_update, tag_fields_to_update = build_field_update_plan(
                fields_to_cols_map,
                set(rating_tag_fields),
                overwrite_existing,
                existing_custom_values,
                existing_tags,
            )

            if not overwrite_existing and not fields_to_run:
                errors[book_id] = "Book already has all fields populated and overwrite is turned off"
                continue

            identifiers = db.get_identifiers(book_id, index_is_id=True)  # type: ignore[attr-defined]
            romanceio_id = identifiers.get(cfg.ID_NAME, None)

            if romanceio_id is None:
                # Search for the book on Romance.io
                title = db.title(book_id, index_is_id=True)  # type: ignore[attr-defined]  # pylint: disable=no-member
                authors = db.authors(book_id, index_is_id=True)  # type: ignore[attr-defined]  # pylint: disable=no-member
                if authors:
                    authors = [x.replace("|", ",") for x in authors.split(",")]

                search_logs: List[str] = []
                romanceio_id = search_with_fallback(
                    title, authors, json_search, html_search, log_func=search_logs.append
                )
                for msg in search_logs:
                    print(f"[{title}] {msg}")

                if romanceio_id:
                    # Don't save here - return it to be saved in main thread
                    # (Worker process DB changes aren't visible to GUI)
                    saved_identifiers[book_id] = romanceio_id
                    print(f"[{title}] Found romanceio identifier {romanceio_id}")
                else:
                    warnings[book_id] = f"Could not find Romance.io ID for: {title}"
                    continue

            books_to_scan.append((book_id, romanceio_id, fields_to_run, custom_fields_to_update, tag_fields_to_update))

        except Exception:  # pylint: disable=broad-except
            errors[book_id] = traceback.format_exc()

    notification(1.0, "Preparation complete")
    return (books_to_scan, warnings, errors, saved_identifiers)


class BookToScan:
    """Represents a book ready to be scanned for Romance.io metadata."""

    def __init__(
        self,
        book_id: int,
        romanceio_id: Optional[str] = None,
        fields_to_run: Optional[List[str]] = None,
        custom_fields_to_update: Optional[List[str]] = None,
        tag_fields_to_update: Optional[List[str]] = None,
    ):
        self.book_id = book_id
        self.romanceio_id = romanceio_id
        self.fields_to_run = fields_to_run if fields_to_run is not None else []
        self.custom_fields_to_update = custom_fields_to_update if custom_fields_to_update is not None else []
        self.tag_fields_to_update = tag_fields_to_update if tag_fields_to_update is not None else []


def call_plugin_callback(plugin_callback: Dict[str, Any], parent: Any, plugin_results: Optional[Any] = None) -> None:
    """
    This function executes a callback to a calling plugin. Because this
    can be called after a job has been run, the plugin and callback function
    are passed as strings.

    The parameters are:

      plugin_callback - This is a dictionary defining the callback function.
          The elements are:
              plugin_name - name of the plugin to be called
              func_name - name of the function to be called
              args - Arguments to be passed to the callback function. Will be
                  passed as "*args" so must be a collection if it is supplied.
              kwargs - Keyword arguments to be passedd to the callback function.
                  Will be passed as "**kargs" so must be a dictionary if it
                  is supplied.

      parent - parent gui needed to find the plugin.

      plugin_results - Results to be passed to the plugin.

    If the kwargs dictionary contains an entry for "plugin_results", the value
    will be replaced by the parameter "plugin_results". This allows the results
    of the called plugin to be passed to the callback.
    """
    from calibre.customize.ui import find_plugin

    plugin = find_plugin(plugin_callback["plugin_name"])
    if plugin is not None:
        callback_func = getattr(plugin.load_actual_plugin(parent), plugin_callback["func_name"])
        args = plugin_callback["args"] if "args" in plugin_callback else []
        kwargs = plugin_callback["kwargs"] if "kwargs" in plugin_callback else {}
        if "plugin_results" in kwargs and plugin_results:
            kwargs["plugin_results"] = plugin_results
        callback_func(*args, **kwargs)


class CustomMasterParallelJob(ParallelJob):
    """Parallel job with tracking for book processing and field results."""

    # Attributes inherited from ParallelJob
    name: str
    description: str
    done: Optional[Dict[int, Dict[str, Any]]]

    def __init__(self, book_id: int, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Additional attributes specific to this usage
        self.book_id: int = book_id
        self.fields_to_run: List[str] = []
        self.custom_fields_to_update: List[str] = []
        self.tag_fields_to_update: List[str] = []
        self.result: Optional[Dict[str, Any]] = None


def do_metadata_download(
    books_to_scan_raw: List[Tuple],
    max_tags: int,
    cpus: Optional[int],  # pylint: disable=unused-argument
    prefer_html: bool = False,
    notification: Callable[[float, str], float] = (lambda x, y: x),
) -> Dict[int, Dict[str, Any]]:
    """
    Master job to launch child jobs to download metadata from Romance.io for this list of books.

    Note: cpus parameter is kept for API compatibility but not used since we force pool_size=1
    for SeleniumBase compatibility.
    """
    job: CustomMasterParallelJob
    # Force pool_size=1 to run jobs sequentially because SeleniumBase undetected Chrome
    # doesn't handle concurrent instances well
    server = Server(pool_size=1)

    books_to_scan = [BookToScan(*book) for book in books_to_scan_raw]

    # Queue all the jobs
    for book_to_scan in books_to_scan:
        args = [
            "calibre_plugins.romanceio_fields.jobs",
            "get_romanceio_fields_for_book",
            (
                book_to_scan.romanceio_id,
                book_to_scan.fields_to_run,
                max_tags,
                prefer_html,
            ),
        ]
        job = CustomMasterParallelJob(
            name="arbitrary",
            description=str(book_to_scan.book_id),
            done=None,
            book_id=book_to_scan.book_id,
            args=args,
        )
        job.fields_to_run = book_to_scan.fields_to_run
        job.custom_fields_to_update = book_to_scan.custom_fields_to_update
        job.tag_fields_to_update = book_to_scan.tag_fields_to_update
        server.add_job(job)

    # This server is an arbitrary_n job, so there is a notifier available.
    # Set the % complete to a small number to avoid the 'unavailable' indicator
    notification(0.01, "Downloading metadata from Romance.io")

    # Dequeue the job results as they arrive, saving the results
    total = len(books_to_scan)
    count = 0
    book_results_map: Dict[int, Dict[str, Any]] = {}
    while True:
        job = server.changed_jobs_queue.get()
        # A job can 'change' when it is not finished, for example if it
        # produces a notification. Ignore these.
        job.update()
        if not job.is_finished:
            continue
        # A job really finished. Get the information.
        assert job.result is not None
        results = job.result
        book_id = job.book_id
        # Print any log lines collected inside the child process so they appear
        # in the calibre job log (child stdout is not captured directly).
        for log_line in results.pop("__log__", []):
            print(log_line)
        # Empty results indicate a failed fetch. Do not attach update instructions,
        # otherwise a failure could be mistaken for a successful empty rating.
        if results:
            results[INTERNAL_CUSTOM_FIELDS_TO_UPDATE] = job.custom_fields_to_update
            results[INTERNAL_TAG_FIELDS_TO_UPDATE] = job.tag_fields_to_update
        book_results_map[book_id] = results
        count = count + 1
        notification(float(count) / total, "Downloading metadata from Romance.io")

        if count >= total:
            break

    server.close()
    return book_results_map


def get_romanceio_fields_for_book(
    romanceio_id: str, fields_to_run: List[str], max_tags: int, prefer_html: bool = False
) -> Dict[str, Any]:
    """Download and parse requested Romance.io fields for a single book."""
    logs: List[str] = []

    def log(msg: str) -> None:
        logs.append(msg)

    def _result(fields: Dict[str, Any]) -> Dict[str, Any]:
        """Attach collected log lines to a result dict and return it."""
        if logs:
            fields["__log__"] = logs
        return fields

    from calibre_plugins.romanceio_fields.common_romanceio_fetch_helper import log_system_info  # type: ignore[import-not-found]  # pylint: disable=import-error

    log_system_info(log)

    try:
        with quick_metadata:
            # Use orchestrator to try JSON first, then HTML fallback with retries
            from calibre_plugins.romanceio_fields.common_romanceio_search_orchestrator import (  # type: ignore[import-not-found]  # pylint: disable=import-error
                fetch_details_with_fallback,
                _is_book_not_found,
            )

            # Create fetch functions without field-specific logic
            if prefer_html:
                # Try Chrome first for the full JS-rendered tag set.
                # On technical failure (Chrome unavailable, driver crash, etc.) fall back
                # to the normal JSON -> SSR orchestrator so the user still gets metadata.
                # On a genuine 404 (book not found), stop immediately.
                log(f"prefer_html=True: fetching Chrome HTML directly for {romanceio_id}")
                try:
                    chrome_result = _fetch_html(romanceio_id, log)
                    if _is_book_not_found(chrome_result):
                        log(f"Romance.io ID {romanceio_id} was not found on the website (404)")
                        return _result({})
                    from calibre_plugins.romanceio_fields.parse_html import parse_fields_from_html  # type: ignore[import-not-found]  # pylint: disable=import-error

                    return _result(
                        _build_fields(parse_fields_from_html(chrome_result, max_tags), fields_to_run, max_tags)
                    )
                except Exception as e:  # pylint: disable=broad-except
                    log(f"Chrome fetch failed ({type(e).__name__}: {e}), falling back to JSON/SSR")

            result = fetch_details_with_fallback(
                romanceio_id=romanceio_id,
                json_fetch_func=_fetch_json,
                lightweight_html_fetch_func=lambda book_id, log_func: _fetch_html_lightweight(
                    book_id, log_func, max_tags=max_tags
                ),
                html_fetch_func=_fetch_html,
                log_func=log,
                max_retries=3,
                retry_delay=2.0,
                # abort= intentionally omitted: this runs in a Calibre child process
                # with no shared threading.Event. Calibre handles cancellation at the
                # process level by terminating the child process.
            )

            if result is None:
                log(f"Failed to fetch data for {romanceio_id}")
                return _result({})

            # Parse result to a common fields dict, then map to calibre field constants
            if _is_book_not_found(result):
                log(f"Romance.io ID {romanceio_id} was not found on the website (404)")
                return _result({})
            if isinstance(result, dict):
                from calibre_plugins.romanceio_fields.parse_json import parse_fields_from_json  # type: ignore[import-not-found]  # pylint: disable=import-error

                parsed_fields = parse_fields_from_json(result)
            elif isinstance(result, _SsrParsedFields):
                parsed_fields = result.fields
            else:
                from calibre_plugins.romanceio_fields.parse_html import parse_fields_from_html  # type: ignore[import-not-found]  # pylint: disable=import-error

                parsed_fields = parse_fields_from_html(result, max_tags)
            return _result(_build_fields(parsed_fields, fields_to_run, max_tags))
    except DRMError:
        log(f"Book {romanceio_id} is DRM-protected, skipping")
        return _result({})
    except (ValueError, TypeError, AttributeError, KeyError, IndexError) as e:
        log(f"Error parsing Romance.io data: {e}")
        log(traceback.format_exc())
        return _result({})
    except Exception as e:  # pylint: disable=broad-except
        log(f"Unexpected error fetching {romanceio_id}: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return _result({})


def _fetch_json(
    romanceio_id: str,
    log_func: Callable,
) -> Optional[Dict[str, Any]]:
    """Fetch book data from JSON API.

    Returns:
        Book JSON dict if successful, None if not found
    Raises:
        Exception on technical failure (network, parsing, etc.)
    """
    from calibre_plugins.romanceio_fields.common_romanceio_json_api import get_book_details_json  # type: ignore[import-not-found]  # pylint: disable=import-error

    book_json = get_book_details_json(romanceio_id, log_func=log_func, timeout=_JSON_REQUEST_TIMEOUT_SECS)
    return book_json


def _fetch_html_lightweight(
    romanceio_id: str,
    log_func: Callable,
    max_tags: int,
) -> Optional[Any]:
    """Fetch and parse book fields using a lightweight HTTP GET (no Chrome).

    Romance.io renders pages server-side. Ratings come from the book-stats
    element (same as Chrome). The legacy combined tags come from the meta
    description attribute, which contains the same slug set as the JSON API
    'tropes' field. Categorized tag copies come from the page's embedded
    rendered and embedded tag groups without changing that legacy combined output.

    Args:
        romanceio_id: Romance.io book identifier.
        log_func: Callback for job-log messages.
        max_tags: Maximum size of the legacy combined tag list.

    Returns:
        _SsrParsedFields with pre-parsed fields, or _BookNotFound if the book was not found (404)
    Raises:
        RuntimeError on technical failure (network, Cloudflare block, etc.)
    """
    from calibre_plugins.romanceio_fields.common_romanceio_search_orchestrator import _BookNotFound  # type: ignore[import-not-found]  # pylint: disable=import-error
    from calibre_plugins.romanceio_fields.common_romanceio_fetch_helper import (  # type: ignore[import-not-found]  # pylint: disable=import-error
        fetch_book_page_http,
        parse_html_from_selenium,
    )
    from calibre_plugins.romanceio_fields.parse_html import parse_fields_from_ssr_html  # type: ignore[import-not-found]  # pylint: disable=import-error

    raw_html, is_valid = fetch_book_page_http(romanceio_id, log_func=log_func, timeout=_JSON_REQUEST_TIMEOUT_SECS)

    if raw_html is None or not is_valid:
        log_func(f"Lightweight HTTP fetch: book {romanceio_id} not found (404)")
        return _BookNotFound()

    root = parse_html_from_selenium(raw_html)

    title_node = root.xpath("//title")
    if title_node:
        page_title = (title_node[0].text or "").strip().lower()
        if "search results for" in page_title:
            log_func(f"Lightweight HTTP fetch: got search results page for {romanceio_id}")
            return _BookNotFound()

    parsed = parse_fields_from_ssr_html(root, max_tags=max_tags)
    return _SsrParsedFields(fields=parsed)


def _fetch_html(
    romanceio_id: str,
    log_func: Callable,
) -> Optional[Any]:
    """Fetch and parse HTML page for book via Chrome browser automation.

    Returns:
        lxml HtmlElement root if successful, _BookNotFound if book not found
    Raises:
        Exception on technical failure (network, parsing, etc.)
    """
    from calibre_plugins.romanceio_fields.common_romanceio_search_orchestrator import _BookNotFound  # type: ignore[import-not-found]  # pylint: disable=import-error
    from calibre_plugins.romanceio_fields.fetch_helper import (  # type: ignore[import-not-found]  # pylint: disable=import-error
        fetch_romanceio_book_page,
    )

    url = f"https://www.romance.io/books/{romanceio_id}"
    raw_html, is_valid = fetch_romanceio_book_page(url, log=log_func)

    if not raw_html:
        # Chrome failed to load the page (timeout, crash, or driver error) - technical failure
        raise RuntimeError(f"Failed to fetch HTML page for {romanceio_id} (Chrome did not return page content)")

    if not is_valid:
        # Page loaded but shows 404 / "page not found" - invalid book ID
        return _BookNotFound()

    from calibre_plugins.romanceio_fields.common_romanceio_fetch_helper import parse_html_from_selenium  # type: ignore[import-not-found]  # pylint: disable=import-error

    root = parse_html_from_selenium(raw_html)

    title_node = root.xpath("//title")
    if title_node:
        page_title = (title_node[0].text or "").strip().lower()
        if "search results for" in page_title:
            log_func(f"Chrome HTML fetch: got search results page instead of book page for {romanceio_id}")
            return _BookNotFound()

    errmsg = root.xpath('//*[@id="errorMessage"]')
    if errmsg:
        from lxml.html import tostring  # type: ignore[import-not-found]  # pylint: disable=import-error

        msg = tostring(errmsg[0], method="text", encoding="unicode").strip()
        raise RuntimeError(f"Page contains error: {msg}")

    return root


def _build_fields(
    parsed_fields: Dict[str, Any],
    fields_to_run: List[str],
    max_tags: int,
) -> Dict[str, Any]:
    """Map pre-parsed fields to calibre field constants.

    Args:
        parsed_fields: Dict with rating keys, the legacy combined tags key,
            and optional categorized tag-list keys
        fields_to_run: List of field constants to include
        max_tags: Maximum number of tags to return

    Returns:
        Dict with field constant keys and formatted values
    """
    # Map generic fields to field constants
    results: Dict[str, Any] = {}

    for field in fields_to_run:
        if field == cfg.FIELD_STEAM_RATING and "steam_rating" in parsed_fields:
            value = parsed_fields["steam_rating"]
            if value is not None:
                results[cfg.FIELD_STEAM_RATING] = int(round(value)) if isinstance(value, float) else int(value)
            else:
                results[cfg.FIELD_STEAM_RATING] = value
        elif field == cfg.FIELD_STAR_RATING and "star_rating" in parsed_fields:
            value = parsed_fields["star_rating"]
            if value is not None:
                # Round to 2 decimal places to match UI display
                results[cfg.FIELD_STAR_RATING] = round(value, 2)
            else:
                results[cfg.FIELD_STAR_RATING] = value
        elif field == cfg.FIELD_RATING_COUNT and "rating_count" in parsed_fields:
            results[cfg.FIELD_RATING_COUNT] = parsed_fields["rating_count"]
        elif field == cfg.FIELD_ROMANCE_TAGS and "tags" in parsed_fields:
            tags = parsed_fields["tags"]
            if isinstance(tags, list) and len(tags) > 0:
                # Take first max_tags, ensuring all are strings
                filtered_tags = [str(tag) for tag in tags[:max_tags]]
                tag_string: str = cfg.TAG_DELIMITER.join(filtered_tags)
                results[cfg.FIELD_ROMANCE_TAGS] = tag_string
        elif field in cfg.CATEGORY_FIELDS:
            parsed_key = cfg.CATEGORY_FIELD_TO_PARSED_KEY[field]
            category_tags = parsed_fields.get(parsed_key)
            if isinstance(category_tags, list):
                # Category columns are complete copies and do not consume or alter
                # the maximum-limited legacy combined tag output.
                results[field] = cfg.TAG_DELIMITER.join(str(tag) for tag in category_tags)

    return results
