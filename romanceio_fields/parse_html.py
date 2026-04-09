"""
HTML parsing functions specific to the romanceio_fields plugin.
Extracts field data from Romance.io book pages.
"""

from typing import List, Optional, Dict, Any
from lxml.html import HtmlElement


def parse_steam_rating(root: HtmlElement) -> Optional[int]:
    """Extract steam/spice rating (1-5) from Romance.io book page."""
    # Look for all is-sr-only spans within book-stats, not just direct children
    steam_elements = root.xpath('//div[@id="main"]//div[@id="book-stats"]//span[@class="is-sr-only"]')

    # Find the one that contains "Steam/Spice level"
    steam_element = None
    for elem in steam_elements:
        text = elem.text_content()
        if "Steam/Spice level:" in text:
            steam_element = elem
            break

    if steam_element is None:
        return None

    steam_str = steam_element.text_content()
    steam = int(steam_str.strip().split("Steam/Spice level:")[1].split("of")[0].strip())
    return steam


def parse_star_rating(root: HtmlElement) -> Optional[float]:
    """Extract user star rating (0-5) from Romance.io book page.

    Returns None if there are no ratings (even though HTML shows a rating of 0.00).
    """
    # First check if there are any ratings at all
    rating_count = parse_rating_count(root)
    if rating_count is None or rating_count == 0:
        return None

    # Star rating is in the first is-sr-only span: "Rated: 4.54 of 5 stars"
    star_elements = root.xpath('//div[@id="main"]//div[@id="book-stats"]//span[@class="is-sr-only"]')
    if not star_elements:
        return None

    # Find the one that contains "Rated:"
    for elem in star_elements:
        text = elem.text_content()
        if "Rated:" in text:
            star_str = text.strip()
            star = float(star_str.split("Rated: ")[1].split(" of")[0])
            return star

    return None


def parse_rating_count(root: HtmlElement) -> Optional[int]:
    """Extract total number of user ratings from Romance.io book page."""
    import re

    # Rating count is in the book-stats div, format: "1351 ratings" or "1 rating"
    stats_text = root.xpath('//div[@id="main"]//div[@id="book-stats"]')[0].text_content()
    match = re.search(r"(\d+)\s+ratings?", stats_text)
    if match:
        rating_count = int(match.group(1))
        return rating_count
    return None


def parse_romance_tags(root: HtmlElement) -> List[str]:
    """
    Extract all tags from Romance.io book page.
    """

    def extract_tags(xpath_expr: str) -> List[str]:
        """Extract tags from elements matching xpath."""
        tags_list = []
        for li_elem in root.xpath(xpath_expr):
            tag_elem = li_elem.xpath('.//a[@class="topic"]')
            if not tag_elem:
                continue
            tag_name = tag_elem[0].text_content().strip()
            tags_list.append(tag_name)
        return tags_list

    tags: List[str] = extract_tags('//ul[@id="valid-topics-list"]//li[@class="tagged-topic"]')
    geo_tags: List[str] = extract_tags('//ul[@id="valid-topics-geography"]//li[@class="tagged-topic"]')
    cw_tags: List[str] = extract_tags('//ul[@id="valid-topics-content-warnings"]//li[@class="tagged-topic"]')
    format_tags: List[str] = extract_tags('//ul[@id="valid-topics-Format"]//li[@class="tagged-topic"]')
    # Also get Format tags without the tagged-topic class (like "audiobook")
    format_tags_simple: List[str] = [
        elem.text_content() for elem in root.xpath('//ul[@id="valid-topics-Format"]//li/a[@class="topic"]')
    ]
    # Combine and deduplicate
    all_format_tags = list(set(format_tags + format_tags_simple))
    return tags + geo_tags + cw_tags + all_format_tags


def parse_fields_from_html(
    root: HtmlElement,
    max_tags: int,
) -> Dict[str, Any]:
    """Parse all fields from HTML page, returning generic dict.

    Args:
        root: lxml HtmlElement root
        max_tags: Maximum number of tags to return

    Returns:
        Dict with generic keys (same format as parse_fields_from_json):
        - steam_rating: Steam/spice rating (1-5 int) or None
        - star_rating: Star rating (0-5 float) or None
        - rating_count: Number of ratings (int) or None
        - tags: List of tag strings
    """
    steam_rating = parse_steam_rating(root)
    star_rating = parse_star_rating(root)
    rating_count = parse_rating_count(root)
    tags = parse_romance_tags(root)[:max_tags]

    return {
        "steam_rating": steam_rating,
        "star_rating": star_rating,
        "rating_count": rating_count,
        "tags": tags,
    }
