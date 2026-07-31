"""
JSON parsing functions specific to the romanceio_fields plugin.
This plugin needs: steam_rating, star_rating, rating_count, tags.
"""

from typing import Any, Dict

from calibre_plugins.romanceio_fields.common_romanceio_tag_mappings import (  # type: ignore[import-not-found]  # pylint: disable=import-error
    categorize_json_tags,
    convert_json_tags_to_display_names,
)


def parse_fields_from_json(book_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parse book fields from JSON API response for romanceio_fields plugin.

    Args:
        book_json: Book dict from JSON API

    Returns:
        Dict with generic parsed fields:
        - steam_rating: Steam/spice rating (1-5 int) or None
        - star_rating: Star rating (0-5 float) or None
        - rating_count: Number of ratings (int) or None
        - tags: List of tag strings
        - general_tags, content_warnings, geography_tags, format_tags:
          Category copies derived from the bundled Romance.io taxonomy
    """
    info = book_json.get("info", {})

    steam_rating = info.get("originalSteamRating")
    if steam_rating == 0:
        # If original is 0, use avg steam rating
        steam_rating = info.get("avgSteamRating")
        if steam_rating:
            # Round to nearest integer for consistency
            steam_rating = round(steam_rating)

    # Convert 0 to None (0 is not a valid steam rating, valid range is 1-5)
    if steam_rating == 0:
        steam_rating = None

    star_rating = info.get("avgRating")
    rating_count = info.get("numRating")

    if rating_count == 0:
        star_rating = None

    raw_tags = book_json.get("tropes", [])
    converted_tags = convert_json_tags_to_display_names(raw_tags)
    categorized_tags = categorize_json_tags(raw_tags)

    return {
        "steam_rating": steam_rating,
        "star_rating": star_rating,
        "rating_count": rating_count,
        "tags": converted_tags,
        **categorized_tags,
    }
