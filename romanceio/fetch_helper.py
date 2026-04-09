"""
Fetch pages using SeleniumBase for the romanceio plugin.
Wraps common fetch_helper with plugin-specific imports.
"""

from .common_romanceio_fetch_helper import (  # pylint: disable=import-error
    fetch_page as _common_fetch_page,
    fetch_romanceio_book_page as _common_fetch_romanceio_book_page,
)


def fetch_page(url, wait_for_element=None, max_wait=30):
    """
    Fetch a page using SeleniumBase with Cloudflare bypass.

    Args:
        url: URL to fetch
        wait_for_element: Optional element to wait for in page source
        max_wait: Maximum seconds to wait for page load

    Returns:
        Page HTML as string, or None on error
    """
    return _common_fetch_page(url, plugin_name="romanceio", wait_for_element=wait_for_element, max_wait=max_wait)


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
