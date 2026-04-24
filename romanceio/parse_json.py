"""
JSON parsing functions specific to the romanceio metadata plugin.
This plugin needs: title, authors, cover_url, series info for book identification.
"""

import re
import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional, Callable

try:
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen  # type: ignore[import-not-found,no-redef]

from calibre_plugins.romanceio.common_romanceio_validation import is_valid_romanceio_id, clean_author_names  # type: ignore[import-not-found]  # pylint: disable=import-error
from calibre_plugins.romanceio.common_romanceio_tag_mappings import convert_json_tags_to_display_names  # type: ignore[import-not-found]  # pylint: disable=import-error


@dataclass
class ParsedBookData:
    """Structured data parsed from Romance.io book sources (JSON or HTML)."""

    romanceio_id: Optional[str] = None
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    cover_url: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[float] = None
    tags: Optional[List[str]] = None
    pubdate: Optional[datetime.datetime] = None
    rating: Optional[float] = None
    description: Optional[str] = None

    # Error handling
    is_valid: bool = True
    error_reason: Optional[str] = None


def get_author_name_from_redirect(author_id: str, timeout: int = 30) -> Optional[str]:
    """
    Get author name by following the redirect on their profile page.

    When the author API returns no books, we can still get the author name
    by requesting their profile URL, which redirects to a slug-based URL.
    Example: /authors/622b054e08b4d931146c53eb redirects to
             /authors/622b054e08b4d931146c53eb/lydia-reeves

    Args:
        author_id: Romance.io author ID
        timeout: Request timeout in seconds

    Returns:
        Author name extracted from redirect URL, or None if failed
    """
    try:
        url = f"https://www.romance.io/authors/{author_id}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        req = Request(url, headers=headers)
        response = urlopen(req, timeout=timeout)

        # Get the final URL after redirect
        final_url = response.geturl()

        # Extract author name slug from URL
        # Expected format: /authors/{id}/{name-slug}
        match = re.search(r"/authors/[^/]+/([^/?#]+)", final_url)
        if match:
            slug = match.group(1)
            # Convert slug to proper name: "lydia-reeves" -> "Lydia Reeves"
            name_parts = slug.split("-")
            author_name = " ".join(word.capitalize() for word in name_parts)
            return author_name

        return None
    except Exception:  # pylint: disable=broad-except
        return None


def parse_book_from_search_json(
    book_json: Dict[str, Any],
    get_author_details_func: Optional[Callable[[str, int], Optional[Dict[str, Any]]]] = None,
) -> Tuple[str, str, List[str], Optional[str], bool, Optional[str]]:
    """
    Parse a book entry from JSON search results for the romanceio plugin.

    Args:
        book_json: Book dict from JSON API
        get_author_details_func: Optional function to fetch author details by ID
            Signature: func(author_id: str, timeout: int) -> Optional[Dict[str, Any]]

    Returns:
        Tuple of (romanceio_id, title, authors, cover_url, is_valid, error_reason)
    """
    romanceio_id = book_json.get("_id", "")

    if not is_valid_romanceio_id(romanceio_id):
        return ("", "", [], None, False, "Invalid Romance.io ID format")

    info = book_json.get("info", {})
    full_title = info.get("title", "")

    title = full_title
    match = re.match(r"^(.+?)\s*\((.+?)\s*#([0-9.]+)\)\s*$", full_title)
    if match:
        title = match.group(1).strip()

    authors = []
    author_ids = book_json.get("authors", [])

    if get_author_details_func and author_ids:
        for author_id in author_ids:
            if isinstance(author_id, dict):
                # Sometimes authors come as objects with _id and name
                author_name = author_id.get("name")
                if author_name:
                    authors.append(author_name)
            elif isinstance(author_id, str):
                # Sometimes authors come as just ID strings, fetch details
                try:
                    author_data = get_author_details_func(author_id, 30)
                    if author_data and "books" in author_data:
                        books = author_data.get("books", [])
                        if books and len(books) > 0:
                            book_authors = books[0].get("authors", [])
                            for auth in book_authors:
                                if isinstance(auth, dict) and auth.get("_id") == author_id:
                                    author_name = auth.get("name")
                                    if author_name:
                                        authors.append(author_name)
                                        break
                        else:
                            # Empty books array - try redirect fallback
                            # This happens when an author profile exists but has no books
                            author_name = get_author_name_from_redirect(author_id, 30)
                            if author_name:
                                authors.append(author_name)
                except Exception:  # pylint: disable=broad-except
                    # If author API call fails or data parsing fails, continue without that author
                    pass

    # Fall back to parsing from title_series if no authors found
    if not authors:
        title_series = info.get("title_series", "")
        if title_series:
            author_part = ""
            if title_series.startswith(title):
                author_part = title_series[len(title) :].strip()
            elif title_series.startswith(full_title):
                author_part = title_series[len(full_title) :].strip()

            # If book is in a series, also remove the series title from what's left
            if author_part:
                series_list = book_json.get("series", [])
                if series_list and isinstance(series_list, list) and len(series_list) > 0:
                    series_title = series_list[0].get("title", "")
                    if series_title and author_part.startswith(series_title):
                        author_part = author_part[len(series_title) :].strip()

                if author_part:
                    # Split multiple authors - they may be separated by comma-space or just space
                    # Try comma-space first (most common)
                    if ", " in author_part:
                        authors = [name.strip() for name in author_part.split(", ")]
                    else:
                        # If no comma, assume single author
                        authors = [author_part]

    # Clean whitespace and filter out blank entries
    authors = clean_author_names(authors)

    cover_url = None
    image = book_json.get("image", {})
    if image:
        img_url = image.get("url", "")
        if img_url:
            if img_url.startswith("http"):
                cover_url = img_url
            else:
                # Construct full S3 URL
                cover_url = f"https://s3.amazonaws.com/romance.io/books/large/{img_url}"

    # Alternative: construct from ID
    if not cover_url and romanceio_id:
        cover_url = f"https://s3.amazonaws.com/romance.io/books/large/{romanceio_id}.jpg"

    return (romanceio_id, title, authors, cover_url, True, None)


def _parse_series_from_json(book_json: Dict[str, Any]) -> Tuple[Optional[str], Optional[float]]:
    """Parse series name and index from the top-level series array.

    The API returns series as: [{"title": "Series Name", "no": 1, "no_display": "1", "series": "id"}]

    Returns:
        Tuple of (series_name, series_index) or (None, None) if no series data
    """
    series_list = book_json.get("series", [])
    if not series_list or not isinstance(series_list, list):
        return None, None
    first = series_list[0]
    if not isinstance(first, dict):
        return None, None
    series_name = first.get("title") or ""
    if not series_name:
        return None, None
    series_index = None
    no = first.get("no")
    if no is not None:
        try:
            series_index = float(no)
        except (ValueError, TypeError):
            pass
    return series_name, series_index


def _parse_pubdate_from_json(book_json: Dict[str, Any]) -> Optional[datetime.datetime]:
    """Parse publish date from info.published Unix timestamp.

    Uses timedelta arithmetic to handle pre-epoch (negative) timestamps,
    which datetime.utcfromtimestamp() rejects on Windows.

    Returns:
        datetime with the full date from the timestamp, or None if unavailable
    """
    published = book_json.get("info", {}).get("published")
    if published is None:
        return None
    try:
        timestamp = int(published)
        epoch = datetime.datetime(1970, 1, 1)
        dt = epoch + datetime.timedelta(seconds=timestamp)
        if dt.year < 1 or dt.year > 9999:
            return None
        from calibre.utils.date import utc_tz

        return datetime.datetime(dt.year, dt.month, dt.day, tzinfo=utc_tz)
    except (ValueError, TypeError, OverflowError):
        return None


def parse_details_from_json(
    book_json: Dict[str, Any],
    get_author_details_func: Optional[Callable[[str, int], Optional[Dict[str, Any]]]] = None,
) -> ParsedBookData:
    """Parse all book details from JSON API response.

    Args:
        book_json: Book dict from JSON API
        get_author_details_func: Optional function to fetch author details by ID

    Returns:
        ParsedBookData object with parsed fields (check is_valid for errors)

    Raises:
        ValueError, TypeError, KeyError, IndexError, AttributeError on parsing errors
    """
    parsed_id, title, authors, cover_url, is_valid, error_reason = parse_book_from_search_json(
        book_json, get_author_details_func
    )

    tags = convert_json_tags_to_display_names(book_json.get("tropes", []))
    series, series_index = _parse_series_from_json(book_json)
    pubdate = _parse_pubdate_from_json(book_json)

    rating = None
    raw_rating = book_json.get("info", {}).get("avgRating")
    if raw_rating is not None:
        try:
            rating = float(raw_rating)
        except (ValueError, TypeError):
            pass

    description = book_json.get("info", {}).get("description") or None

    return ParsedBookData(
        romanceio_id=parsed_id,
        title=title,
        authors=authors,
        cover_url=cover_url,
        series=series,
        series_index=series_index,
        tags=tags if tags else None,
        pubdate=pubdate,
        rating=rating,
        description=description,
        is_valid=is_valid,
        error_reason=error_reason,
    )
