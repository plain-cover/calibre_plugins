"""
HTML parsing utility functions for the romanceio metadata plugin.
"""

import re
import datetime
from typing import List, Optional, Tuple, Dict, Callable

from lxml.html import HtmlElement
from calibre.utils.cleantext import clean_ascii_chars
from calibre_plugins.romanceio.parse_json import ParsedBookData  # type: ignore[import-not-found]  # pylint: disable=import-error

from calibre_plugins.romanceio.common_romanceio_validation import is_valid_romanceio_id, clean_author_names  # type: ignore[import-not-found]  # pylint: disable=import-error


def clean_html(raw):
    """Clean and normalize HTML content."""
    from calibre.ebooks.chardet import xml_to_unicode

    return clean_ascii_chars(xml_to_unicode(raw, strip_encoding_pats=True, resolve_entities=True, assume_utf8=True)[0])


def parse_html(raw):
    """Parse HTML using html5_parser or html5lib fallback."""
    try:
        from html5_parser import parse
    except ImportError:
        # Old versions of calibre
        import html5lib

        return html5lib.parse(raw, treebuilder="lxml", namespaceHTMLElements=False)
    return parse(raw)


def parse_romanceio_id(url: str) -> Optional[str]:
    """Extract and validate Romance.io book ID from URL.

    Romance.io URLs are: /books/{mongodb_id}/book-title-author

    Returns:
        Valid ID string, or None if no ID found or ID format is invalid
    """
    match = re.search(r"/books/([a-f0-9]+)", url)
    if match:
        romanceio_id = match.group(1)
        if not is_valid_romanceio_id(romanceio_id):
            return None
        return romanceio_id
    return None


def parse_title(root: HtmlElement, log_func: Optional[Callable] = None) -> str:
    """Extract book title from Romance.io book page.

    Removes series information if present (e.g., "Title (Series #1)" -> "Title").
    """
    title_text = root.xpath('//div[@id="main"]//div[contains(@class, "book-info")]/h1')[0].text_content().strip()
    if log_func:
        log_func("parse_title (raw): ", title_text)
    # Remove series information if present (e.g., "Title (Series #1)" -> "Title")
    # Match pattern: anything in parentheses at the end
    match = re.match(r"^(.+?)\s*\([^)]+\)\s*$", title_text)
    if match:
        title = match.group(1).strip()
    else:
        title = title_text
    if log_func:
        log_func("parse_title (cleaned): ", title)
    return title


def parse_series_from_title(
    root: HtmlElement, log_func: Optional[Callable] = None
) -> Tuple[Optional[str], Optional[float]]:
    """Extract series name and index from title element.

    Title format: "Book Title (Series Name #3)"

    Returns:
        Tuple of (series_name, series_index) or (None, None) if no series info
    """
    title_text = root.xpath('//div[@id="main"]//div[contains(@class, "book-info")]/h1')[0].text_content().strip()
    # Match pattern: "Title (Series Name #N)"
    match = re.match(r"^.+?\s*\((.+?)\s*#([0-9.]+)\)\s*$", title_text)
    if match:
        series_name = match.group(1).strip()
        try:
            series_index = float(match.group(2))
            if log_func:
                log_func(f"parse_series_from_title: series_name='{series_name}', series_index='{series_index}'")
            return (series_name, series_index)
        except ValueError:
            pass
    return (None, None)


def parse_authors(root: HtmlElement, log_func: Optional[Callable] = None) -> List[str]:
    """Extract author name(s) from Romance.io book page.

    Handles multiple authors separated by commas.
    Preserves UTF-8 characters (accents, smart quotes, etc.).
    """
    author = (
        root.xpath('//div[@id="main"]//div[contains(@class, "book-info")]/h2[contains(@class, "author")]')[0]
        .text_content()
        .strip()
    )

    # Split by comma in case multiple authors are in one field
    # e.g., "Yumoyori Wilson, Avery Phoenix" -> ["Yumoyori Wilson", "Avery Phoenix"]
    if ", " in author:
        authors = [name.strip() for name in author.split(", ")]
    else:
        authors = [author]

    # Clean whitespace and filter out blank entries
    authors = clean_author_names(authors)

    if log_func:
        log_func("parse_authors: ", authors)
    return authors


def parse_star_rating(root: HtmlElement) -> float:
    """Extract star rating from Romance.io book page.

    Returns rating as a float (e.g., 4.54).
    """
    star_str = root.xpath('//div[@id="main"]//div[@id="book-stats"]/span[@class="is-sr-only"][1]')[0].text_content()
    star = float(star_str.strip().split("Rated: ")[1].split(" of")[0])
    return star


def parse_rating_count(root: HtmlElement) -> Optional[int]:
    """Extract total number of user ratings from Romance.io book page."""
    stats_text = root.xpath('//div[@id="main"]//div[@id="book-stats"]')[0].text_content()
    match = re.search(r"(\d+)\s+ratings?", stats_text)
    if match:
        rating_count = int(match.group(1))
        return rating_count
    return None


def parse_publish_date(root: HtmlElement, log_func: Optional[Callable] = None) -> Optional[datetime.datetime]:
    """Extract publish date from Romance.io book page.

    Handles two formats:
      - Full date: "435 pages · Published: 23 Apr 2024"
      - Year only: "435 pages · Published: 1813"

    Returns:
        datetime object with the full date when available, or January 1st of the
        year when only the year is present. Returns None if not found.
    """
    _month_abbrs = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    try:
        stats_scnd = root.xpath('//span[@class="book-stats-scnd"]')[0].text_content()
        from calibre.utils.date import utc_tz

        # Try full date first: "23 Apr 2024"
        full_match = re.search(r"Published:.*?(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", stats_scnd)
        if full_match:
            day = int(full_match.group(1))
            month = _month_abbrs.get(full_match.group(2).lower())
            year = int(full_match.group(3))
            if month:
                pub_date = datetime.datetime(year, month, day, tzinfo=utc_tz)
                if log_func:
                    log_func(f"parse_publish_date: {pub_date}")
                return pub_date

        # Fall back to year only: "1813"
        year_match = re.search(r"Published:.*?(\d{4})", stats_scnd)
        if year_match:
            year = int(year_match.group(1))
            pub_date = datetime.datetime(year, 1, 1, tzinfo=utc_tz)
            if log_func:
                log_func(f"parse_publish_date: {pub_date}")
            return pub_date
    except (IndexError, ValueError):
        pass
    return None


def parse_tags(root: HtmlElement, log_func: Optional[Callable] = None) -> List[str]:
    """Extract tags from Romance.io topic lists.

    Combines tags from regular topics, geography, content warnings, and format sections.

    Returns:
        List of tag strings (raw tags without any mapping applied)
    """
    tags = [
        elem.text_content()
        for elem in root.xpath('//ul[@id="valid-topics-list"]//li[@class="tagged-topic"]//a[@class="topic"]')
    ]
    geo_tags = [
        elem.text_content()
        for elem in root.xpath('//ul[@id="valid-topics-geography"]//li[@class="tagged-topic"]//a[@class="topic"]')
    ]
    cw_tags = [
        elem.text_content()
        for elem in root.xpath(
            '//ul[@id="valid-topics-content-warnings"]//li[@class="tagged-topic"]//a[@class="topic"]'
        )
    ]
    format_tags = [
        elem.text_content()
        for elem in root.xpath('//ul[@id="valid-topics-Format"]//li[@class="tagged-topic"]//a[@class="topic"]')
    ]
    format_tags_simple = [
        elem.text_content() for elem in root.xpath('//ul[@id="valid-topics-Format"]//li/a[@class="topic"]')
    ]
    # Combine and deduplicate
    all_format_tags = list(set(format_tags + format_tags_simple))
    all_tags = tags + geo_tags + cw_tags + all_format_tags
    if log_func:
        log_func(f"parse_tags: found {len(all_tags)} tags")
    return all_tags


def convert_genres_to_calibre_tags(
    genre_tags: List[str], map_genres: bool, calibre_tag_map: Dict[str, List[str]]
) -> List[str]:
    """Convert Romance.io genre tags to Calibre tags using configured mapping.

    Args:
        genre_tags: List of raw Romance.io tag strings
        map_genres: If False, returns genre_tags unchanged
        calibre_tag_map: Dictionary mapping lowercase genre tags to list of Calibre tags

    Returns:
        List of Calibre tag strings (or original tags if mapping disabled)
    """
    if not map_genres:
        # User has disabled Romance.io tag filtering/mapping - all genres become tags
        return genre_tags

    calibre_tag_map_lower = dict((k.lower(), v) for (k, v) in calibre_tag_map.items())
    tags_to_add = []
    for genre_tag in genre_tags:
        tags = calibre_tag_map_lower.get(genre_tag.lower(), None)
        if tags:
            for tag in tags:
                if tag not in tags_to_add:
                    tags_to_add.append(tag)
    return list(tags_to_add)


def _extract_description_parts(container: HtmlElement) -> List[str]:
    """Extract description text parts from a Romance.io description container element.

    The description text appears as ``tail`` on child elements: first on the
    mobile cover thumbnail (.book-cover-container), then on a series of <br>
    elements that act as paragraph separators.  The steam-rating note
    (.desc-steam-rating) is excluded.
    """
    parts: List[str] = []

    # Text before the first child element (rare but handle it)
    if container.text and container.text.strip():
        parts.append(container.text.strip())

    for child in container:
        child_class = child.get("class") or ""
        tag = child.tag if isinstance(child.tag, str) else ""

        if "book-cover-container" in child_class:
            # Description text starts as the tail of the cover thumbnail
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
        elif "desc-steam-rating" in child_class:
            # Skip the steam-rating note and its tail entirely
            pass
        elif tag == "br":
            # Emit one <br/> per <br> element — two consecutive <br>s in the
            # source (Romance.io's paragraph separator) become <br/><br/>.
            parts.append("<br/>")
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
        else:
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())

    return parts


def parse_description(root: HtmlElement, log_func: Optional[Callable] = None) -> Optional[str]:
    """Extract book description/synopsis from book-description div.

    Romance.io wraps the description in a structure like:
        #book-description > .is-clearfix > [0+ anonymous divs] > div

    The innermost div directly contains a mobile cover thumbnail
    (.book-cover-container) whose tail holds the first description segment,
    followed by <br> elements whose tails hold subsequent segments, and a
    steam-rating note (.desc-steam-rating) which is always excluded.

    Rather than assuming a fixed nesting depth, we locate the container by
    finding whichever div inside .is-clearfix directly parents .book-cover-container.

    Returns:
        HTML string suitable for mi.comments, or None if not found.
    """
    # Find the div that directly parents .book-cover-container, regardless of depth.
    containers = root.xpath(
        '//div[@id="book-description"]'
        '//div[contains(@class,"is-clearfix")]'
        '//div[div[contains(@class,"book-cover-container")]]'
    )
    if not containers:
        if log_func:
            book_desc = root.xpath('//div[@id="book-description"]')
            if not book_desc:
                log_func("parse_description: #book-description not found")
            else:
                clearfix = root.xpath('//div[@id="book-description"]//div[contains(@class,"is-clearfix")]')
                if not clearfix:
                    log_func("parse_description: .is-clearfix not found inside #book-description")
                else:
                    log_func(
                        "parse_description: .book-cover-container not found inside .is-clearfix "
                        f"(clearfix children: {[c.get('class') or c.tag for c in clearfix[0]]})"
                    )
        return None

    parts = _extract_description_parts(containers[0])
    if not parts:
        if log_func:
            log_func(
                "parse_description: found container but no description text "
                f"(children: {[c.get('class') or c.tag for c in containers[0]]})"
            )
        return None

    description = "".join(parts).strip()
    if log_func:
        log_func(f"parse_description: extracted {len(description)} characters")
    return description


def parse_details_from_html(url: str, root: HtmlElement, log_func: Optional[Callable] = None) -> ParsedBookData:
    """Parse all book details from HTML page.

    Args:
        url: The Romance.io book URL (for ID extraction)
        root: lxml HtmlElement root
        log_func: Optional logging function

    Returns:
        ParsedBookData object with all parsed fields
    """
    result = ParsedBookData()

    try:
        result.romanceio_id = parse_romanceio_id(url)
    except (ValueError, TypeError, AttributeError):
        if log_func:
            log_func(f"Error parsing Romance.io id for url: {url!r}")

    try:
        result.title = parse_title(root, log_func)
    except (ValueError, TypeError, IndexError, AttributeError):
        if log_func:
            log_func(f"Error parsing title for url: {url!r}")

    try:
        result.authors = parse_authors(root, log_func)
    except (ValueError, TypeError, IndexError, AttributeError):
        if log_func:
            log_func(f"Error parsing authors for url: {url!r}")

    try:
        series, series_index = parse_series_from_title(root, log_func)
        result.series = series
        result.series_index = series_index
    except (ValueError, TypeError, OSError):
        if log_func:
            log_func(f"Error parsing series for url: {url!r}")

    try:
        result.tags = parse_tags(root, log_func)
    except (ValueError, TypeError, IndexError, AttributeError, KeyError):
        if log_func:
            log_func(f"Error parsing tags for url: {url!r}")

    try:
        result.pubdate = parse_publish_date(root, log_func)
    except (ValueError, TypeError, IndexError, AttributeError):
        if log_func:
            log_func(f"Error parsing publish date for url: {url!r}")

    try:
        result.rating = parse_star_rating(root)
    except (ValueError, TypeError, IndexError, AttributeError):
        if log_func:
            log_func(f"Error parsing star rating for url: {url!r}")

    try:
        result.description = parse_description(root, log_func)
    except (ValueError, TypeError, IndexError, AttributeError):
        if log_func:
            log_func(f"Error parsing description for url: {url!r}")

    return result
