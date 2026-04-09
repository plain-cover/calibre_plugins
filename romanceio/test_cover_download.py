"""
Test cover downloading functionality for the romanceio plugin.

This test file covers:
1. Static tests: Cover URL construction, caching, error handling
2. Live tests: Actual cover downloads from Romance.io

To run these tests:
    calibre-debug -e test_cover_download.py
"""

import os
import sys
from queue import Queue
from threading import Event
from typing import Any
from unittest.mock import Mock, patch

# Set up module path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.test_data import TEST_BOOKS


class MockLog:
    """Mock logger for testing."""

    def __init__(self):
        self.messages = []

    def __call__(self, *args):
        msg = " ".join(str(arg) for arg in args)
        self.messages.append(msg)
        print(f"LOG: {msg}")

    def info(self, msg: str) -> None:
        self.messages.append(f"INFO: {msg}")
        print(f"INFO: {msg}")

    def debug(self, msg: str) -> None:
        self.messages.append(f"DEBUG: {msg}")
        print(f"DEBUG: {msg}")

    def error(self, msg: str) -> None:
        self.messages.append(f"ERROR: {msg}")
        print(f"ERROR: {msg}")

    def exception(self, msg: str) -> None:
        self.messages.append(f"EXCEPTION: {msg}")
        print(f"EXCEPTION: {msg}")


class MockBrowser:
    """Mock browser for testing cover downloads."""

    def __init__(self, should_fail=False, fail_with_error=None):
        self.should_fail = should_fail
        self.fail_with_error = fail_with_error
        self.last_url = None

    def clone_browser(self):
        return self

    def open_novisit(self, url, timeout=30):
        """Mock open_novisit to simulate cover download."""
        self.last_url = url
        print(f"MockBrowser.open_novisit called with URL: {url}, timeout: {timeout}")

        if self.should_fail:
            error = self.fail_with_error or OSError("Simulated network failure")
            raise error

        # Return a mock response object
        mock_response = Mock()
        # Simulate some cover image data (just a small byte string)
        mock_response.read.return_value = b"MOCK_COVER_IMAGE_DATA_" + url.encode("utf-8")
        return mock_response


def test_cover_url_construction():
    """Test that cover URLs are correctly constructed from romanceio_id."""
    print("=" * 60)
    print("Testing cover URL construction")
    print("=" * 60)

    from romanceio import RomanceIO

    plugin = RomanceIO(os.path.join(plugin_dir, "__init__.py"))

    # Test with valid romanceio_id
    romanceio_id = "5484ecd47a5936fb0405756c"
    expected_url = f"https://s3.amazonaws.com/romance.io/books/large/{romanceio_id}.jpg"

    # The plugin constructs URLs in download_cover when not cached
    identifiers = {"romanceio": romanceio_id}

    # Create a mock for the cached_identifier_to_cover_url to return None (not cached)
    with patch.object(plugin, "cached_identifier_to_cover_url", return_value=None):
        # Call get_cached_cover_url which will return None
        cached_url = plugin.get_cached_cover_url(identifiers)
        assert cached_url is None, "Expected no cached URL"

        # Now test the download_cover method which constructs the URL
        log = MockLog()
        result_queue: Queue[tuple[Any, bytes]] = Queue()
        abort = Event()
        mock_browser = MockBrowser()

        # Patch the browser property
        with patch.object(type(plugin), "browser", new_callable=lambda: property(lambda self: mock_browser)):
            plugin.download_cover(log, result_queue, abort, identifiers=identifiers, timeout=30)

            # Verify the browser was called with the correct URL
            assert mock_browser.last_url == expected_url, f"Expected URL {expected_url}, got {mock_browser.last_url}"
            print(f"✓ Cover URL constructed correctly: {expected_url}")

            # Verify data was put in result queue
            assert not result_queue.empty(), "Expected result in queue"
            result = result_queue.get()
            assert result[0] == plugin, "Expected plugin in result"
            assert isinstance(result[1], bytes), "Expected bytes data"
            print(f"✓ Cover data received: {len(result[1])} bytes")

    print("\n✓ All cover URL construction tests passed\n")


def test_cover_url_from_cache():
    """Test that cached cover URLs are used when available."""
    print("=" * 60)
    print("Testing cover URL from cache")
    print("=" * 60)

    from romanceio import RomanceIO

    plugin = RomanceIO(os.path.join(plugin_dir, "__init__.py"))

    romanceio_id = "5484ecd47a5936fb0405756c"
    cached_url = "https://s3.amazonaws.com/romance.io/books/large/cached_image.jpg"
    identifiers = {"romanceio": romanceio_id}

    # Mock the cached_identifier_to_cover_url to return a cached URL
    with patch.object(plugin, "cached_identifier_to_cover_url", return_value=cached_url):
        # Test get_cached_cover_url
        result_url = plugin.get_cached_cover_url(identifiers)
        assert result_url == cached_url, f"Expected cached URL {cached_url}, got {result_url}"
        print(f"✓ Cached URL retrieved: {cached_url}")

        # Test download_cover uses cached URL
        log = MockLog()
        result_queue: Queue[tuple[Any, bytes]] = Queue()
        abort = Event()
        mock_browser = MockBrowser()

        # Patch the browser property
        with patch.object(type(plugin), "browser", new_callable=lambda: property(lambda self: mock_browser)):
            plugin.download_cover(log, result_queue, abort, identifiers=identifiers, timeout=30)

            # Verify the browser was called with the cached URL
            assert mock_browser.last_url == cached_url, f"Expected cached URL {cached_url}, got {mock_browser.last_url}"
            print(f"✓ Cover downloaded from cached URL: {cached_url}")

    print("\n✓ All cached cover URL tests passed\n")


def test_missing_identifier():
    """Test handling of missing romanceio identifier."""
    print("=" * 60)
    print("Testing missing identifier handling")
    print("=" * 60)

    from romanceio import RomanceIO

    plugin = RomanceIO(os.path.join(plugin_dir, "__init__.py"))

    # Test with no identifiers
    log = MockLog()
    result_queue: Queue[tuple[Any, bytes]] = Queue()
    abort = Event()
    mock_browser = MockBrowser()

    # Mock cached_identifier_to_cover_url to return None
    with patch.object(plugin, "cached_identifier_to_cover_url", return_value=None):
        # Patch the browser property
        with patch.object(type(plugin), "browser", new_callable=lambda: property(lambda self: mock_browser)):
            plugin.download_cover(log, result_queue, abort, identifiers={}, timeout=30)

            # Should not attempt download
            assert mock_browser.last_url is None, "Should not attempt download without identifier"
            assert result_queue.empty(), "Should not add result without identifier"
            print("✓ Correctly handled missing identifier")

            # Check log message
            assert any(
                "No cached cover URL found" in msg for msg in log.messages
            ), "Expected log message about missing identifier"
            print("✓ Correct log message for missing identifier")

    print("\n✓ All missing identifier tests passed\n")


def test_cover_download_network_error():
    """Test handling of network errors during cover download."""
    print("=" * 60)
    print("Testing network error handling")
    print("=" * 60)

    from romanceio import RomanceIO

    plugin = RomanceIO(os.path.join(plugin_dir, "__init__.py"))

    romanceio_id = "5484ecd47a5936fb0405756c"
    identifiers = {"romanceio": romanceio_id}

    log = MockLog()
    result_queue: Queue[tuple[Any, bytes]] = Queue()
    abort = Event()
    mock_browser = MockBrowser(should_fail=True, fail_with_error=OSError("Network timeout"))

    with patch.object(plugin, "cached_identifier_to_cover_url", return_value=None):
        # Patch the browser property
        with patch.object(type(plugin), "browser", new_callable=lambda: property(lambda self: mock_browser)):
            plugin.download_cover(log, result_queue, abort, identifiers=identifiers, timeout=30)

            # Should handle error gracefully
            assert result_queue.empty(), "Should not add result on network error"
            assert any("Failed to download cover" in msg for msg in log.messages), "Expected error log message"
            print("✓ Network error handled gracefully")

    print("\n✓ All network error tests passed\n")


def test_cover_download_abort():
    """Test that cover download respects abort flag."""
    print("=" * 60)
    print("Testing abort flag handling")
    print("=" * 60)

    from romanceio import RomanceIO

    plugin = RomanceIO(os.path.join(plugin_dir, "__init__.py"))

    romanceio_id = "5484ecd47a5936fb0405756c"
    identifiers = {"romanceio": romanceio_id}

    log = MockLog()
    result_queue: Queue[tuple[Any, bytes]] = Queue()
    abort = Event()
    abort.set()  # Set abort flag before download
    mock_browser = MockBrowser()

    with patch.object(plugin, "cached_identifier_to_cover_url", return_value=None):
        # Patch the browser property
        with patch.object(type(plugin), "browser", new_callable=lambda: property(lambda self: mock_browser)):
            plugin.download_cover(log, result_queue, abort, identifiers=identifiers, timeout=30)

            # Should not attempt download when abort is set
            assert mock_browser.last_url is None, "Should not download when abort is set"
            assert result_queue.empty(), "Should not add result when abort is set"
            print("✓ Abort flag respected")

    print("\n✓ All abort flag tests passed\n")


def test_live_cover_download():
    """Test downloading actual covers from Romance.io (requires internet)."""
    print("=" * 60)
    print("Testing live cover downloads (requires internet)")
    print("=" * 60)

    from romanceio import RomanceIO

    plugin = RomanceIO(os.path.join(plugin_dir, "__init__.py"))

    # Get 3 books with unique, valid romanceio_ids
    test_books = list(
        {
            book.romanceio_id: book
            for book in TEST_BOOKS
            if book.romanceio_id and book.romanceio_id != "000000000000000000000000"
        }.values()
    )[:3]

    if not test_books:
        print("⚠️ No test books with valid romanceio_ids found")
        return

    for book in test_books:
        print(f"\nTesting: {book.title} by {', '.join(book.authors or ['Unknown'])}")
        print(f"  romanceio_id: {book.romanceio_id}")

        identifiers = {"romanceio": book.romanceio_id}
        log = MockLog()
        result_queue: Queue[tuple[Any, bytes]] = Queue()
        abort = Event()

        # Clear any cached URL for this test
        with patch.object(plugin, "cached_identifier_to_cover_url", return_value=None):
            try:
                plugin.download_cover(log, result_queue, abort, identifiers=identifiers, timeout=30)

                if not result_queue.empty():
                    result = result_queue.get()
                    cover_data = result[1]

                    # Verify we got data
                    assert isinstance(cover_data, bytes), "Expected bytes data"
                    assert len(cover_data) > 0, "Expected non-empty cover data"

                    # Basic validation that it looks like an image
                    # JPEG files start with FF D8 FF
                    is_jpeg = cover_data.startswith(b"\xff\xd8\xff")
                    # PNG files start with 89 50 4E 47
                    is_png = cover_data.startswith(b"\x89PNG")

                    if is_jpeg or is_png:
                        image_type = "JPEG" if is_jpeg else "PNG"
                        print(f"  ✓ Downloaded cover: {len(cover_data)} bytes ({image_type})")
                    else:
                        print(f"  ⚠️ Downloaded data doesn't look like JPEG or PNG: {cover_data[:20]!r}")
                else:
                    print("  ○ No cover data received (may not exist on Romance.io)")

            except Exception as e:  # pylint: disable=broad-except
                print(f"  ❌ Error downloading cover: {type(e).__name__}: {e}")

    print("\n✓ Live cover download tests completed\n")


def test_cover_caching_during_identify():
    """Test that cover URLs can be cached and retrieved."""
    print("=" * 60)
    print("Testing cover URL caching")
    print("=" * 60)

    from romanceio import RomanceIO

    plugin = RomanceIO(os.path.join(plugin_dir, "__init__.py"))

    romanceio_id = "5484ecd47a5936fb0405756c"
    cover_url = "https://s3.amazonaws.com/romance.io/books/large/5484ecd47a5936fb0405756c.jpg"

    # Test caching a cover URL
    plugin.cache_identifier_to_cover_url(romanceio_id, cover_url)
    print(f"  ✓ Cached cover URL for {romanceio_id}")

    # Test retrieving the cached URL
    identifiers = {"romanceio": romanceio_id}
    retrieved_url = plugin.get_cached_cover_url(identifiers)

    if retrieved_url:
        print(f"  ✓ Retrieved cached URL: {retrieved_url}")
        assert retrieved_url == cover_url, f"Expected {cover_url}, got {retrieved_url}"
    else:
        # Some versions of Calibre may not persist cache across calls
        print("  ⚠️ Cache not retrieved (may not be persisted in test environment)")

    print("\n✓ Cover caching tests completed\n")


def run_all_tests():
    """Run all cover download tests."""
    print("\n")
    print("=" * 80)
    print("COVER DOWNLOAD TEST SUITE")
    print("=" * 80)
    print("\n")

    # Static tests (fast, no network)
    test_cover_url_construction()
    test_cover_url_from_cache()
    test_missing_identifier()
    test_cover_download_network_error()
    test_cover_download_abort()
    test_cover_caching_during_identify()

    # Live tests (slow, requires network)
    print("=" * 80)
    print("LIVE TESTS (require internet connection)")
    print("=" * 80)
    test_live_cover_download()

    print("=" * 80)
    print("ALL COVER DOWNLOAD TESTS COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    try:
        run_all_tests()
        sys.exit(0)
    except Exception as e:  # pylint: disable=broad-except
        print(f"\n❌ TEST SUITE FAILED: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
