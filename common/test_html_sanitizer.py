"""
Tests for sanitize_html_for_lxml() in common_romanceio_fetch_helper.

Verifies that XML 1.0 illegal characters (which Selenium's page_source can inject)
are stripped before the HTML is passed to lxml.html.fromstring().

Run: calibre-debug common/test_html_sanitizer.py
"""

import sys
import os
from lxml.html import HtmlElement, fromstring

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.common_romanceio_fetch_helper import sanitize_html_for_lxml  # type: ignore[import-not-found]  # pylint: disable=import-error


def _parse(html_str: str) -> HtmlElement:
    return fromstring(sanitize_html_for_lxml(html_str))


def test_clean_html_unchanged():
    """Normal HTML without illegal chars round-trips correctly."""
    root = _parse("<html><body><p>Hello world</p></body></html>")
    assert root.xpath("//p")[0].text_content() == "Hello world"
    print("✓ clean HTML round-trips correctly")


def test_returns_bytes():
    """sanitize_html_for_lxml returns bytes so lxml receives them in lenient mode."""
    assert isinstance(sanitize_html_for_lxml("<html></html>"), bytes)
    print("✓ returns bytes")


def test_lxml_does_not_raise_on_selenium_html():
    """Canonical regression: all illegal char classes that Selenium can inject via third-party JS."""
    dirty = (
        "<html><head>"
        '<meta name="description" content="text\x00null \x0bvtab \x0cff \x1fus \ufffe\uffff">'
        "</head><body><h1>Test Book</h1></body></html>"
    )
    try:
        root = _parse(dirty)
        assert root.xpath("//h1")[0].text_content() == "Test Book"
        print("✓ lxml does not raise XMLSyntaxError on sanitized Selenium HTML")
    except Exception as e:
        raise AssertionError(f"lxml raised {type(e).__name__}: {e}") from e


def run_all_tests():
    tests = [test_clean_html_unchanged, test_returns_bytes, test_lxml_does_not_raise_on_selenium_html]
    passed = failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:  # pylint: disable=broad-except
            print(f"✗ {test.__name__}: {e}")
            failed += 1
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
