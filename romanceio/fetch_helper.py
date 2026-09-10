"""
Fetch pages through supervised browsers for the romanceio plugin.
Wraps common fetch_helper with plugin-specific imports.
"""

from .common_romanceio_fetch_helper import (  # pylint: disable=import-error
    fetch_page as _common_fetch_page,
    fetch_romanceio_book_page as _common_fetch_romanceio_book_page,
)


def fetch_page(
    url,
    wait_for_element=None,
    not_found_marker=None,
    secondary_wait_element=None,
    max_wait=30,
    log_func=None,
    abort=None,
):
    """
    Fetch a rendered page using Qt WebEngine, then Chrome on failure.

    Args:
        url: URL to fetch
        wait_for_element: Optional element to wait for in page source
        not_found_marker: Optional string; if found while waiting for wait_for_element,
            return the page immediately instead of timing out.
        secondary_wait_element: Optional string; after wait_for_element is found, keep
            polling for this element within remaining time before returning. The page
            must contain populated search results to count as successful.
        max_wait: Maximum seconds to wait for page load
        log_func: Optional logging function to route browser errors to calibre's job log

    Returns:
        Page HTML as a string. Browser failures raise BrowserFetchError.
    """
    return _common_fetch_page(
        url,
        plugin_name="romanceio",
        wait_for_element=wait_for_element,
        not_found_marker=not_found_marker,
        secondary_wait_element=secondary_wait_element,
        max_wait=max_wait,
        log_func=log_func,
        abort=abort,
    )


def fetch_romanceio_book_page(url, log=None, prefer_chrome=False):
    """
    Fetch a Romance.io book page with validation.

    Args:
        url: Romance.io book URL to fetch
        log: Optional logger for messages
        prefer_chrome: Try Chrome before Qt WebEngine when True

    Returns:
        Tuple of (page_html, is_valid):
            - page_html: HTML string or None on error
            - is_valid: True if valid book page, False if 404/invalid
    """
    return _common_fetch_romanceio_book_page(url, plugin_name="romanceio", log=log, prefer_chrome=prefer_chrome)
