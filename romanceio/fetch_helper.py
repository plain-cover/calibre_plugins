"""
Fetch pages using SeleniumBase for the romanceio plugin.
Wraps common fetch_helper with plugin-specific imports.
"""

from .common_romanceio_fetch_helper import (  # pylint: disable=import-error
    fetch_page as _common_fetch_page,
    fetch_romanceio_book_page as _common_fetch_romanceio_book_page,
)


def fetch_page(url, wait_for_element=None, not_found_marker=None, max_wait=30, log_func=None):
    """
    Fetch a page using SeleniumBase with Cloudflare bypass.

    Args:
        url: URL to fetch
        wait_for_element: Optional element to wait for in page source
        not_found_marker: Optional string; if found while waiting for wait_for_element,
            return the page immediately instead of timing out.
        max_wait: Maximum seconds to wait for page load
        log_func: Optional logging function to route Chrome errors to calibre's job log

    Returns:
        Page HTML as string, or None on error
    """
    return _common_fetch_page(
        url,
        plugin_name="romanceio",
        wait_for_element=wait_for_element,
        not_found_marker=not_found_marker,
        max_wait=max_wait,
        log_func=log_func,
    )


def fetch_romanceio_book_page(url, log=None):
    """
    Fetch a Romance.io book page with validation.

    Args:
        url: Romance.io book URL to fetch
        log: Optional logger for messages

    Returns:
        Tuple of (page_html, is_valid):
            - page_html: HTML string or None on error
            - is_valid: True if valid book page, False if 404/invalid
    """
    return _common_fetch_romanceio_book_page(url, plugin_name="romanceio", log=log)
