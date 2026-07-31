"""
HTML parsing functions specific to the romanceio_fields plugin.
Extracts field data from Romance.io book pages.
"""

import json
import re
from typing import List, Optional, Dict, Any
from lxml.html import HtmlElement
from .common_romanceio_tag_mappings import (  # pylint: disable=import-error
    categorize_json_tags,
    convert_json_tags_to_display_names,
)


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
    try:
        steam = int(steam_str.strip().split("Steam/Spice level:")[1].split("of")[0].strip())
    except (ValueError, IndexError):
        return None
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
    # Rating count is in the book-stats div, format: "1351 ratings" or "1 rating"
    nodes = root.xpath('//div[@id="main"]//div[@id="book-stats"]')
    if not nodes:
        return None
    stats_text = nodes[0].text_content()
    match = re.search(r"(\d+)\s+ratings?", stats_text)
    if match:
        rating_count = int(match.group(1))
        return rating_count
    return None


def _parse_embedded_tag_categories(root: HtmlElement) -> Optional[Dict[str, List[str]]]:
    """Parse Romance.io's server-provided ``tagged_topics`` JavaScript object."""
    for script_text in root.xpath("//script/text()"):
        assignment = re.search(r"\b(?:var|let|const)\s+tagged_topics\s*=\s*", script_text)
        if not assignment:
            continue
        try:
            tagged_topics, _ = json.JSONDecoder().raw_decode(script_text[assignment.end() :].lstrip())
        except (TypeError, ValueError):
            continue
        if not isinstance(tagged_topics, dict):
            continue

        def extract_group(source_key: str) -> List[str]:
            values: List[str] = []
            group = tagged_topics.get(source_key, [])
            if not isinstance(group, list):
                return values
            for item in group:
                if isinstance(item, dict):
                    value = item.get("title") or item.get("topic")
                else:
                    value = item
                if not isinstance(value, str):
                    continue
                value = value.strip()
                if value:
                    values.append(value)
            return values

        return {
            "general_tags": extract_group("list"),
            "content_warnings": extract_group("content warnings"),
            "geography_tags": extract_group("geography"),
            "format_tags": extract_group("Format"),
        }
    return None


def _merge_unique(primary: List[str], additional: List[str]) -> List[str]:
    """Append missing values without changing the existing rendered-page order."""
    merged = list(primary)
    seen = set(primary)
    for value in additional:
        if value not in seen:
            merged.append(value)
            seen.add(value)
    return merged


def _has_rendered_tag_category_lists(root: HtmlElement) -> bool:
    """Return whether the page contains the rendered category containers."""
    return bool(
        root.xpath(
            '//ul[@id="valid-topics-list" or @id="valid-topics-content-warnings" '
            'or @id="valid-topics-geography" or @id="valid-topics-Format"]'
        )
    )


def has_tag_category_data(root: HtmlElement) -> bool:
    """Return whether the page exposes either embedded or rendered category data."""
    return _has_rendered_tag_category_lists(root) or _parse_embedded_tag_categories(root) is not None


def _parse_rendered_tag_categories(root: HtmlElement) -> Dict[str, List[str]]:
    """Extract categories from the rendered lists used by the legacy parser."""
    def extract_tags(xpath_expr: str) -> List[str]:
        """Extract tags from elements matching xpath."""
        tags_list = []
        for li_elem in root.xpath(xpath_expr):
            tag_elem = li_elem.xpath('.//a[@class="topic"]')
            if not tag_elem:
                continue
            tag_name = tag_elem[0].text_content().strip()
            if tag_name:
                tags_list.append(tag_name)
        return tags_list

    general_tags: List[str] = extract_tags('//ul[@id="valid-topics-list"]//li[@class="tagged-topic"]')
    geography_tags: List[str] = extract_tags('//ul[@id="valid-topics-geography"]//li[@class="tagged-topic"]')
    content_warnings: List[str] = extract_tags(
        '//ul[@id="valid-topics-content-warnings"]//li[@class="tagged-topic"]'
    )
    format_tags: List[str] = extract_tags('//ul[@id="valid-topics-Format"]//li[@class="tagged-topic"]')
    # Also get Format tags without the tagged-topic class (like "audiobook")
    format_tags_simple: List[str] = []
    for elem in root.xpath('//ul[@id="valid-topics-Format"]//li/a[@class="topic"]'):
        tag_name = elem.text_content().strip()
        if tag_name:
            format_tags_simple.append(tag_name)
    # Combine and deduplicate
    all_format_tags = list(dict.fromkeys(format_tags + format_tags_simple))
    rendered_categories = {
        "general_tags": general_tags,
        "content_warnings": content_warnings,
        "geography_tags": geography_tags,
        "format_tags": all_format_tags,
    }
    return rendered_categories


def _merge_tag_categories(
    rendered_categories: Dict[str, List[str]],
    embedded_categories: Optional[Dict[str, List[str]]],
) -> Dict[str, List[str]]:
    """Merge rendered and embedded category values without changing their order."""
    if embedded_categories is None:
        return rendered_categories

    return {
        key: _merge_unique(rendered_categories[key], embedded_categories[key])
        for key in rendered_categories
    }


def _supplement_categories_from_slugs(
    categories: Dict[str, List[str]],
    raw_slugs: List[str],
) -> Dict[str, List[str]]:
    """Fill partial page categories from description/API-equivalent slugs."""
    if not raw_slugs:
        return categories

    return _merge_tag_categories(categories, categorize_json_tags(raw_slugs))


def parse_tag_categories_from_html(root: HtmlElement) -> Dict[str, List[str]]:
    """Extract Romance.io tags in the categories used on the book page."""
    return _merge_tag_categories(
        _parse_rendered_tag_categories(root),
        _parse_embedded_tag_categories(root),
    )


def _combine_rendered_tag_categories(categories: Dict[str, List[str]]) -> List[str]:
    """Flatten rendered categories in the legacy combined-column order."""
    return (
        categories["general_tags"]
        + categories["geography_tags"]
        + categories["content_warnings"]
        + categories["format_tags"]
    )


def parse_tags_from_js_html(root: HtmlElement) -> List[str]:
    """Extract the legacy combined tag list from a Romance.io book page."""
    # Keep this function on the exact rendered-list path it used before category
    # columns were introduced. Embedded data supplements only the optional copies.
    return _combine_rendered_tag_categories(_parse_rendered_tag_categories(root))


def _parse_ratings(root: HtmlElement) -> Dict[str, Any]:
    """Parse steam, star, and rating count from the book-stats element."""
    return {
        "steam_rating": parse_steam_rating(root),
        "star_rating": parse_star_rating(root),
        "rating_count": parse_rating_count(root),
    }


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
        - tags: Legacy combined list of tag strings
        - general_tags, content_warnings, geography_tags, format_tags:
          Separate category lists copied from the website
    """
    rendered_categories = _parse_rendered_tag_categories(root)
    combined_tags = _combine_rendered_tag_categories(rendered_categories)
    result = {**_parse_ratings(root), "tags": combined_tags[:max_tags]}
    rendered_categories_present = _has_rendered_tag_category_lists(root)
    embedded_categories = _parse_embedded_tag_categories(root)
    raw_slugs = _parse_tag_slugs_from_description(root)
    if rendered_categories_present or embedded_categories is not None:
        # Category columns are complete copies of the website groups. Keep the
        # longstanding rendered-list behavior of the combined column separate.
        result.update(
            _supplement_categories_from_slugs(
                _merge_tag_categories(rendered_categories, embedded_categories),
                raw_slugs,
            )
        )
    elif raw_slugs:
        result.update(categorize_json_tags(raw_slugs))
    return result


def _parse_tag_slugs_from_description(root: HtmlElement) -> List[str]:
    """Extract raw tag slugs from the page's description metadata."""
    meta_nodes = root.xpath('//meta[@name="description"]/@content')
    if not meta_nodes:
        return []

    tag_match = re.search(r"is tagged as ([^.]+)\.", meta_nodes[0])
    if not tag_match:
        return []
    return [slug.strip() for slug in tag_match.group(1).split(", ") if slug.strip()]


def parse_tags_from_description(root: HtmlElement) -> List[str]:
    """Extract and display-map tags from the description metadata.

    Romance.io's description text lists tag slugs in the format:
    "'BookTitle' is tagged as slug1, slug2, slug3."
    These slugs are identical to the JSON API 'tropes' field, so the returned
    display names exactly match what parse_fields_from_json() returns for tags.

    This is the correct tag source for lightweight HTTP (SSR) responses: the
    client-side JavaScript adds extra community-voted tags to the page, but
    the description meta tag (server-side) always matches the JSON API.

    Args:
        root: lxml HtmlElement root

    Returns:
        List of display name strings (slug -> display mapped)
    """
    return convert_json_tags_to_display_names(_parse_tag_slugs_from_description(root))


def parse_fields_from_ssr_html(root: HtmlElement, max_tags: int = 100) -> Dict[str, Any]:
    """Parse all fields from a server-side rendered (SSR) HTML page.

    Romance.io renders book pages server-side. Ratings are in the book-stats
    element (same as Chrome-rendered pages). Tags appear as slugs in the
    meta description attribute - the same underlying source as the JSON API
    'tropes' field - so this function produces results equivalent to the JSON API:

    - steam_rating, star_rating, rating_count: identical to Chrome parsing
    - tags: identical to JSON API tags (Chrome adds extra community-voted tags via JS)

    Args:
        root: lxml HtmlElement root parsed from a plain HTTP response
        max_tags: Maximum number of tags to return

    Returns:
        Dict with the same generic keys as parse_fields_from_json:
        - steam_rating: Steam/spice rating (1-5 int) or None
        - star_rating: Star rating (0-5 float) or None
        - rating_count: Number of ratings (int) or None
        - tags: List of display name strings, preserving the existing JSON-equivalent output
        - general_tags, content_warnings, geography_tags, format_tags:
          Separate category lists copied from the server-rendered page sections
    """
    combined_tags = parse_tags_from_description(root)
    result = {
        **_parse_ratings(root),
        "tags": combined_tags[:max_tags],
    }
    rendered_categories = _parse_rendered_tag_categories(root)
    rendered_categories_present = _has_rendered_tag_category_lists(root)
    embedded_categories = _parse_embedded_tag_categories(root)
    raw_slugs = _parse_tag_slugs_from_description(root)
    if rendered_categories_present or embedded_categories is not None:
        # Category columns mirror the groups visible on the website, while the
        # legacy combined column remains API-equivalent and maximum-limited.
        result.update(
            _supplement_categories_from_slugs(
                _merge_tag_categories(rendered_categories, embedded_categories),
                raw_slugs,
            )
        )
    elif raw_slugs:
        # Older/minimal pages may not expose category groups. Classify their
        # API-equivalent description slugs as a compatibility fallback.
        result.update(categorize_json_tags(raw_slugs))
    return result
