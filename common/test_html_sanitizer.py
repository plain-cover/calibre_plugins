"""
Tests for sanitize_html_for_lxml() in common_romanceio_fetch_helper.

Verifies that XML 1.0 illegal characters (which Selenium's page_source can inject)
are stripped before the HTML is passed to lxml.html.fromstring().

Run: calibre-debug common/test_html_sanitizer.py
"""

import sys
import os
from lxml.html import HtmlElement

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.common_romanceio_fetch_helper import sanitize_html_for_lxml, parse_html_from_selenium  # type: ignore[import-not-found]  # pylint: disable=import-error


def _parse(html_str: str) -> HtmlElement:
    return parse_html_from_selenium(html_str)


def test_clean_html_unchanged():
    """Normal HTML without illegal chars round-trips correctly."""
    root = _parse("<html><body><p>Hello world</p></body></html>")
    assert root.xpath("//p")[0].text_content() == "Hello world"
    print("✓ clean HTML round-trips correctly")


def test_returns_str():
    """sanitize_html_for_lxml still returns str (used as a standalone sanitizer)."""
    result = sanitize_html_for_lxml("<html></html>")
    assert isinstance(result, str)
    print("✓ sanitize_html_for_lxml returns str")


def test_parse_html_from_selenium_returns_element():
    """parse_html_from_selenium returns an lxml HtmlElement."""
    root = parse_html_from_selenium("<html><body><p>Hi</p></body></html>")
    assert root is not None
    assert root.xpath("//p")[0].text_content() == "Hi"
    print("✓ parse_html_from_selenium returns HtmlElement")


def test_unicode_preserved():
    """Non-ASCII characters (smart quotes, accented, CJK) are not corrupted."""
    cases = [
        ("Bellamy\u2019s Triumph", "Bellamy\u2019s Triumph"),
        ("\u014ckami", "\u014ckami"),
        ("\uad8c\uac78\uc744", "\uad8c\uac78\uc744"),
        ("Ren\u00e9e", "Ren\u00e9e"),
    ]
    for input_str, expected in cases:
        html = f"<html><body><p>{input_str}</p></body></html>"
        root = parse_html_from_selenium(html)
        got = root.xpath("//p")[0].text_content()
        assert got == expected, f"Expected {expected!r}, got {got!r}"
    print("✓ non-ASCII characters preserved")


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


def test_lone_surrogate_handled():
    """Lone surrogates (Windows Selenium page_source quirk) don't cause XMLSyntaxError."""
    # Construct a str with a lone surrogate via surrogateescape
    lone_surrogate = b"before\x80after".decode("utf-8", errors="surrogateescape")
    html = f"<html><body><h1>{lone_surrogate}</h1></body></html>"
    try:
        root = _parse(html)
        assert root.xpath("//h1") is not None
        print("✓ lone surrogate handled without XMLSyntaxError")
    except Exception as e:
        raise AssertionError(f"lxml raised {type(e).__name__} on lone surrogate: {e}") from e


def run_all_tests():
    tests = [
        test_clean_html_unchanged,
        test_returns_str,
        test_parse_html_from_selenium_returns_element,
        test_unicode_preserved,
        test_lxml_does_not_raise_on_selenium_html,
        test_lone_surrogate_handled,
    ]
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
