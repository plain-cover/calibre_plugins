from threading import Thread

from lxml.html import tostring

from calibre.ebooks.metadata.book.base import Metadata
from calibre.library.comments import sanitize_comments_html  # type: ignore[import-not-found]  # pylint: disable=import-error
import calibre_plugins.romanceio.config as cfg  # type: ignore[import-not-found]  # pylint: disable=import-error
from calibre_plugins.romanceio.parse_html import (  # type: ignore[import-not-found]  # pylint: disable=import-error
    parse_romanceio_id,
    convert_genres_to_calibre_tags,
)


class Worker(Thread):
    """
    Get book details from Romance.io book page in a separate thread
    """

    def __init__(self, url, result_queue, browser, log, relevance, plugin, timeout=20, search_fallback=None):
        Thread.__init__(self)
        self.daemon = True
        self.url, self.result_queue = url, result_queue
        self.log, self.timeout = log, timeout
        self.relevance, self.plugin = relevance, plugin
        self.browser = browser.clone_browser()
        self.cover_url = None
        self.romanceio_id = None
        self.search_fallback = search_fallback or {}

    def run(self):
        try:
            self.get_details()
        except Exception:  # pylint: disable=broad-except
            self.log.exception(f"get_details failed for url: {self.url!r}")

    def get_details(self):
        """Fetch book details, trying JSON API first, then falling back to HTML scraping."""
        try:
            romanceio_id = parse_romanceio_id(self.url)
            if not romanceio_id:
                self.log.error(f"Could not extract valid romanceio_id from URL: {self.url!r}")
                return
        except (ValueError, TypeError, AttributeError):
            self.log.exception(f"Error parsing Romance.io id from url: {self.url!r}")
            return

        # Use orchestrator to try JSON first, then HTML fallback with retries
        from calibre_plugins.romanceio.common_romanceio_search_orchestrator import (  # type: ignore[import-not-found]  # pylint: disable=import-error
            fetch_details_with_fallback,
        )

        result = fetch_details_with_fallback(
            romanceio_id=romanceio_id,
            json_fetch_func=self._fetch_json,
            html_fetch_func=self._fetch_html,
            log_func=self.log.info,
            max_retries=3,
            retry_delay=2.0,
        )

        if result is None:
            # Both JSON API and HTML scraping failed. If we captured basic metadata
            # from the search step (e.g. Chrome not installed), emit a minimal result
            # so the book still appears as a Romance.io match in calibre.
            fallback_title = self.search_fallback.get("title", "")
            fallback_authors = self.search_fallback.get("authors", [])
            if fallback_title and fallback_authors:
                self.log.info(f"Detail fetch failed - using search result as minimal fallback for {romanceio_id}")
                self._build_minimal_metadata(romanceio_id, fallback_title, fallback_authors)
            else:
                self.log.error(f"Failed to fetch details for {romanceio_id} from {self.url!r}")
            return

        # Result could be JSON dict or HTML root element
        if isinstance(result, dict):
            self._build_metadata_from_json(romanceio_id, result)
        else:
            # It's an HTML root element
            self._build_metadata_from_html(result)

    def _fetch_json(self, romanceio_id, log_func):
        """Fetch book details from JSON API.

        Returns:
            Book dict if successful, None if not found
        Raises:
            Exception on technical failure (network, parsing, etc.)
        """
        from calibre_plugins.romanceio.common_romanceio_json_api import get_book_details_json  # type: ignore[import-not-found]  # pylint: disable=import-error

        book_json = get_book_details_json(romanceio_id, log_func=log_func, timeout=30)
        return book_json

    def _fetch_html(self, romanceio_id, log_func):
        """Fetch and parse HTML page for book details.

        Returns:
            lxml root element if successful, None if not found
        Raises:
            Exception on technical failure (network, parsing, etc.)
        """
        from calibre_plugins.romanceio.common_romanceio_fetch_helper import (  # type: ignore[import-not-found]  # pylint: disable=import-error
            fetch_romanceio_book_page,
        )

        log_func(f"HTML fetch: requesting book page for {romanceio_id}")
        page_html, is_valid = fetch_romanceio_book_page(self.url, plugin_name="romanceio", log=self.log)

        if not is_valid:
            if not page_html:
                raise RuntimeError(f"Chrome failed to fetch page for {romanceio_id}: {self.url}")
            log_func(f"HTML fetch: page is invalid (404 or wrong content) for {romanceio_id}")
            return None

        log_func(f"HTML fetch: parsing {len(page_html)} bytes of HTML for {romanceio_id}")
        from calibre_plugins.romanceio.common_romanceio_fetch_helper import parse_html_from_selenium  # type: ignore[import-not-found]  # pylint: disable=import-error

        root = parse_html_from_selenium(page_html)

        title_node = root.xpath("//title")
        if title_node:
            page_title = (title_node[0].text or "").strip()
            if "search results for" in page_title:
                log_func(f"HTML fetch: got search results page instead of book page for {romanceio_id}")
                return None

        errmsg = root.xpath('//*[@id="errorMessage"]')
        if errmsg:
            msg = tostring(errmsg, method="text", encoding="unicode").strip()
            raise RuntimeError(f"Page contains error: {msg}")

        log_func(f"HTML fetch: page validated, extracting metadata for {romanceio_id}")
        return root

    def _build_minimal_metadata(self, romanceio_id, title, authors):
        """Build a minimal Metadata object from search-result data when full detail fetch fails.

        This ensures the book still appears as a Romance.io match in calibre even when
        Chrome is not installed (or any other permanent detail-fetch failure), so the
        user at least gets the ID link and cover.
        """
        mi = Metadata(title, authors)
        mi.set_identifier("romanceio", romanceio_id)
        self.romanceio_id = romanceio_id

        # Cover URL is predictable from the ID even without fetching the detail page
        cover_url = f"https://s3.amazonaws.com/romance.io/books/large/{romanceio_id}.jpg"
        self.cover_url = cover_url
        self.plugin.cache_identifier_to_cover_url(romanceio_id, cover_url)

        mi.source_relevance = self.relevance
        self.plugin.clean_downloaded_metadata(mi)
        self.result_queue.put(mi)

    def _build_metadata_from_json(self, romanceio_id, book_json):
        """Build Calibre Metadata object from JSON API response."""
        from calibre_plugins.romanceio.parse_json import parse_details_from_json  # type: ignore[import-not-found]  # pylint: disable=import-error
        from calibre_plugins.romanceio.common_romanceio_json_api import get_author_details_json  # type: ignore[import-not-found]  # pylint: disable=import-error

        try:
            parsed = parse_details_from_json(book_json, get_author_details_json)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            self.log.exception(f"Error parsing JSON for book: {romanceio_id}")
            return

        if not parsed.title or not parsed.authors or not parsed.romanceio_id:
            self.log.error(f"Could not parse title/authors/id from JSON for: {romanceio_id}")
            self.log.error(f"Found - ID: {parsed.romanceio_id!r} Title: {parsed.title!r} Authors: {parsed.authors!r}")
            return

        mi = Metadata(parsed.title, parsed.authors)
        self.log.info(f"_build_metadata_from_json - romanceio_id: {parsed.romanceio_id}, mi: \n{mi}")
        mi.set_identifier("romanceio", parsed.romanceio_id)
        self.romanceio_id = parsed.romanceio_id

        if parsed.cover_url:
            self.cover_url = parsed.cover_url

        self._apply_parsed_fields(mi, parsed)

        mi.source_relevance = self.relevance

        if self.cover_url is not None:
            self.plugin.cache_identifier_to_cover_url(self.romanceio_id, self.cover_url)
        self.plugin.clean_downloaded_metadata(mi)

        self.log.info(f"_build_metadata_from_json - final mi.pubdate: {mi.pubdate!r}")
        self.result_queue.put(mi)

    def _build_metadata_from_html(self, root):
        """Build Calibre Metadata object from parsed HTML."""
        from calibre_plugins.romanceio.parse_html import parse_details_from_html  # type: ignore[import-not-found]  # pylint: disable=import-error

        parsed = parse_details_from_html(self.url, root, self.log.info)

        if not parsed.title or not parsed.authors or not parsed.romanceio_id:
            self.log.error(f"Could not parse all of title/authors/romanceio id from: {self.url!r}")
            self.log.error(
                f"Found Romance.io id: {parsed.romanceio_id!r} Title: {parsed.title!r} Authors: {parsed.authors!r}"
            )
            return

        mi = Metadata(parsed.title, parsed.authors)
        self.log.info(f"_build_metadata_from_html - romanceio_id: {parsed.romanceio_id}, mi: {mi}")
        mi.set_identifier("romanceio", parsed.romanceio_id)
        self.romanceio_id = parsed.romanceio_id

        self._apply_parsed_fields(mi, parsed)

        mi.source_relevance = self.relevance

        cover_url = f"https://s3.amazonaws.com/romance.io/books/large/{parsed.romanceio_id}.jpg"
        self.cover_url = cover_url
        self.plugin.cache_identifier_to_cover_url(self.romanceio_id, cover_url)

        self.plugin.clean_downloaded_metadata(mi)

        self.log.info(f"_build_metadata_from_html - final mi.pubdate: {mi.pubdate!r}")
        self.result_queue.put(mi)

    def _apply_parsed_fields(self, mi, parsed):
        """Apply series, tags, pubdate, rating, and comments from parsed data to a Metadata object."""
        if "series" in self.plugin.touched_fields:
            if parsed.series is not None:
                self.log.info(f"Series: {parsed.series!r} (index: {parsed.series_index!r})")
                mi.series = parsed.series
            if parsed.series_index is not None:
                mi.series_index = parsed.series_index  # type: ignore[assignment]

        if "tags" in self.plugin.touched_fields:
            if parsed.tags:
                self.log.info(f"Tags from Romance.io ({len(parsed.tags)}): {parsed.tags}")
                map_genres = cfg.plugin_prefs[cfg.STORE_NAME].get(
                    cfg.KEY_MAP_GENRES, cfg.DEFAULT_STORE_VALUES[cfg.KEY_MAP_GENRES]
                )
                calibre_tag_map = {}
                if map_genres:
                    calibre_tag_map = cfg.plugin_prefs[cfg.STORE_NAME].get(
                        cfg.KEY_GENRE_MAPPINGS, cfg.DEFAULT_STORE_VALUES[cfg.KEY_GENRE_MAPPINGS]
                    )
                tags = convert_genres_to_calibre_tags(parsed.tags, map_genres, calibre_tag_map)
                if tags:
                    self.log.info(f"Final tags ({len(tags)}): {tags}")
                    mi.tags = tags
                else:
                    self.log.info("Tags after mapping: none (all filtered out)")
            else:
                self.log.info("Tags from Romance.io: none")

        if "pubdate" in self.plugin.touched_fields:
            if parsed.pubdate:
                self.log.info(f"setting pubdate: {parsed.pubdate}")
                mi.pubdate = parsed.pubdate
            else:
                self.log.info("pubdate not found")

        if "rating" in self.plugin.touched_fields:
            if parsed.rating is not None:
                mi.rating = int(float(parsed.rating) + 0.5)
                self.log.info(f"setting rating: {mi.rating} (source: {parsed.rating})")

        if "comments" in self.plugin.touched_fields:
            if parsed.description:
                mi.comments = sanitize_comments_html(parsed.description)
                self.log.info(f"setting comments ({len(mi.comments)} chars)")
