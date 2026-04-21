"""
Jobs are tasks that run in a separate process.
We use jobs to manage downloading fields from Romance.io.
"""

import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple


from calibre.customize.ui import quick_metadata
from calibre.ebooks import DRMError
from calibre.utils.ipc.server import Server
from calibre.utils.ipc.job import ParallelJob

from . import config as cfg


def prepare_books_for_download(
    book_ids: List[int],
    fields_to_cols_map: Dict[str, str],
    overwrite_existing: bool,
    db_path: str,
    notification: Callable[[float, str], float] = (lambda x, y: x),
) -> Tuple[List[Tuple], Dict[int, str], Dict[int, str], Dict[int, str]]:
    """
    Prepare books for downloading by searching for Romance.io IDs if needed.
    Returns (books_to_scan_raw, warnings, errors, saved_identifiers) where:
    - books_to_scan_raw: List of tuples ready for do_metadata_download
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

    def json_search(title, authors, log_func):
        from calibre_plugins.romanceio_fields.common_romanceio_json_api import search_books_json  # type: ignore[import-not-found]  # pylint: disable=import-error
        from calibre_plugins.romanceio_fields.common_romanceio_search import find_best_json_match  # type: ignore[import-not-found]  # pylint: disable=import-error

        books = search_books_json(title, authors, 30, log_func)
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
            fields_to_run = []
            for field, col_name in fields_to_cols_map.items():
                if not col_name:
                    continue
                lbl = labels_map[col_name]
                existing_val = db.get_custom(book_id, label=lbl, index_is_id=True)
                if overwrite_existing or existing_val is None or existing_val == 0:
                    fields_to_run.append(field)

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

                romanceio_id = search_with_fallback(title, authors, json_search, html_search, log_func=print)

                if romanceio_id:
                    # Don't save here - return it to be saved in main thread
                    # (Worker process DB changes aren't visible to GUI)
                    saved_identifiers[book_id] = romanceio_id
                    print(f"Found romanceio identifier {romanceio_id} for book {book_id}")
                else:
                    warnings[book_id] = f"Could not find Romance.io ID for: {title}"
                    continue

            books_to_scan.append((book_id, romanceio_id, fields_to_run))

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
    ):
        self.book_id = book_id
        self.romanceio_id = romanceio_id
        self.fields_to_run = fields_to_run if fields_to_run is not None else []

    def to_tuple(self) -> Tuple[int, Optional[str], List[str]]:
        """Convert to tuple format for job processing."""
        return (self.book_id, self.romanceio_id, self.fields_to_run)


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

    try:
        iterator = None

        with quick_metadata:
            try:
                # Use orchestrator to try JSON first, then HTML fallback with retries
                from calibre_plugins.romanceio_fields.common_romanceio_search_orchestrator import (  # type: ignore[import-not-found]  # pylint: disable=import-error
                    fetch_details_with_fallback,
                )

                # Create fetch functions without field-specific logic
                def fetch_json(rid, log_func):
                    return _fetch_json(rid, log_func)

                def fetch_html(rid, log_func):
                    return _fetch_html(rid, log_func)

                if prefer_html:
                    # Skip JSON API and fetch directly from the website for exact tag matching
                    log(f"prefer_html=True: fetching HTML directly for {romanceio_id}")
                    result = _fetch_html(romanceio_id, log)
                    if result is None:
                        log(f"Failed to fetch HTML data for {romanceio_id}")
                        return _result({})
                    return _result(_build_fields(result, fields_to_run, max_tags, from_json=False))

                result = fetch_details_with_fallback(
                    romanceio_id=romanceio_id,
                    json_fetch_func=fetch_json,
                    html_fetch_func=fetch_html,
                    log_func=log,
                    max_retries=3,
                    retry_delay=2.0,
                )

                if result is None:
                    log(f"Failed to fetch data for {romanceio_id}")
                    return _result({})

                # Result is either JSON dict or HTML root element
                if isinstance(result, dict):
                    if result.get("invalid_romanceio_id"):
                        log(f"Romance.io ID {romanceio_id} was not found on the website (404)")
                        return _result({})
                    return _result(_build_fields(result, fields_to_run, max_tags, from_json=True))
                # It's an HTML root element
                return _result(_build_fields(result, fields_to_run, max_tags, from_json=False))
            finally:
                if iterator:
                    iterator.__exit__()
                    iterator = None
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

    book_json = get_book_details_json(romanceio_id, log_func=log_func, timeout=30)
    return book_json


def _fetch_html(
    romanceio_id: str,
    log_func: Callable,
) -> Optional[Any]:
    """Fetch and parse HTML page for book.

    Returns:
        lxml HtmlElement root if successful, dict with {"invalid_romanceio_id": True} if not found
    Raises:
        Exception on technical failure (network, parsing, etc.)
    """
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
        return {"invalid_romanceio_id": True}

    from calibre_plugins.romanceio_fields.common_romanceio_fetch_helper import parse_html_from_selenium  # type: ignore[import-not-found]  # pylint: disable=import-error

    root = parse_html_from_selenium(raw_html)
    return root


def _build_fields(
    data: Any,
    fields_to_run: List[str],
    max_tags: int,
    from_json: bool,
) -> Dict[str, Any]:
    """Build field results from parsed data (JSON or HTML).

    Args:
        data: Either book_json dict or lxml HtmlElement root
        fields_to_run: List of field constants to include
        max_tags: Maximum number of tags to return
        from_json: True if data is JSON dict, False if HTML root

    Returns:
        Dict with field constant keys and formatted values
    """
    if not from_json and isinstance(data, dict) and data.get("invalid_romanceio_id"):
        return data

    if from_json:
        from calibre_plugins.romanceio_fields.parse_json import parse_fields_from_json  # type: ignore[import-not-found]  # pylint: disable=import-error

        parsed_fields = parse_fields_from_json(data)
    else:
        from calibre_plugins.romanceio_fields.parse_html import parse_fields_from_html  # type: ignore[import-not-found]  # pylint: disable=import-error

        parsed_fields = parse_fields_from_html(data, max_tags)

    # Map generic fields to field constants
    results: Dict[str, Any] = {}

    for field in fields_to_run:
        if field == cfg.FIELD_STEAM_RATING and "steam_rating" in parsed_fields:
            value = parsed_fields["steam_rating"]
            if value is not None:
                results[cfg.FIELD_STEAM_RATING] = int(round(value)) if isinstance(value, float) else int(value)
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

    return results
