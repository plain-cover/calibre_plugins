"""Formatting and reconciliation helpers for calibre rating tags."""

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


FIELD_STEAM_RATING = "SteamRating"
FIELD_STAR_RATING = "StarRating"

STEAM_TAG_PREFIX = "Romance.io steam: "
STAR_TAG_PREFIX = "Romance.io stars: "

RATING_TAG_PREFIXES = {
    FIELD_STEAM_RATING: STEAM_TAG_PREFIX,
    FIELD_STAR_RATING: STAR_TAG_PREFIX,
}

RATING_TAG_PATTERNS = {
    FIELD_STEAM_RATING: re.compile(
        r"^Romance\.io steam: [1-5](?:/5)?$",
        re.IGNORECASE,
    ),
    FIELD_STAR_RATING: re.compile(
        r"^Romance\.io stars: (?:[0-4](?:\.\d+)?|5(?:\.0+)?)(?:/5)?$",
        re.IGNORECASE,
    ),
}


def normalize_calibre_tags(tags: Any) -> List[str]:
    """Return tags from either calibre's legacy string or new-API iterable form."""
    if tags is None:
        return []
    if isinstance(tags, str):
        values: Iterable[Any] = tags.split(",")
    else:
        values = tags
    return [str(tag).strip() for tag in values if str(tag).strip()]


def format_rating_tag(field: str, value: Any) -> Optional[str]:
    """Format a fetched rating as a plugin-owned calibre tag."""
    if value is None or field not in RATING_TAG_PREFIXES:
        return None

    try:
        rating = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

    minimum = Decimal("1") if field == FIELD_STEAM_RATING else Decimal("0")
    if not rating.is_finite() or not minimum <= rating <= Decimal("5"):
        return None

    if field == FIELD_STEAM_RATING:
        display_value = format(rating.quantize(Decimal("1"), rounding=ROUND_HALF_UP), "f")
    else:
        rounded_value = rating.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        display_value = format(rounded_value, "f")
    return f"{RATING_TAG_PREFIXES[field]}{display_value}"


def is_owned_rating_tag(tag: str, field: str) -> bool:
    """Return whether ``tag`` is a valid current or legacy plugin rating tag."""
    pattern = RATING_TAG_PATTERNS.get(field)
    return pattern is not None and pattern.fullmatch(tag.strip()) is not None


def has_rating_tag(tags: Any, field: str) -> bool:
    """Return whether a tag list contains a plugin-owned tag for ``field``."""
    return any(is_owned_rating_tag(tag, field) for tag in normalize_calibre_tags(tags))


def build_field_update_plan(
    fields_to_cols_map: Dict[str, str],
    rating_tag_fields: Set[str],
    overwrite_existing: bool,
    existing_custom_values: Dict[str, Any],
    existing_tags: Any,
) -> Tuple[List[str], List[str], List[str]]:
    """Choose sources to fetch and destinations to update for one book."""
    custom_fields_to_update: List[str] = []
    tag_fields_to_update: List[str] = []

    for field, col_name in fields_to_cols_map.items():
        if col_name:
            existing_value = existing_custom_values.get(field)
            if overwrite_existing or existing_value is None or existing_value == 0:
                custom_fields_to_update.append(field)

        if field in rating_tag_fields and (
            overwrite_existing or not has_rating_tag(existing_tags, field)
        ):
            tag_fields_to_update.append(field)

    fields_to_run = [
        field
        for field in fields_to_cols_map
        if field in custom_fields_to_update or field in tag_fields_to_update
    ]
    return fields_to_run, custom_fields_to_update, tag_fields_to_update


def reconcile_rating_tags(tags: Any, values: Dict[str, Any], fields_to_update: Set[str]) -> List[str]:
    """Replace selected plugin-owned rating tags while preserving all other tags."""
    replacement_tags: Dict[str, Optional[str]] = {}
    for field in (FIELD_STEAM_RATING, FIELD_STAR_RATING):
        if field not in fields_to_update or field not in values:
            continue

        value = values[field]
        new_tag = format_rating_tag(field, value)
        if value is not None and new_tag is None:
            # An invalid remote value must not remove a previously stored rating.
            continue
        replacement_tags[field] = new_tag

    updated = [
        tag
        for tag in normalize_calibre_tags(tags)
        if not any(is_owned_rating_tag(tag, field) for field in replacement_tags)
    ]

    for field in (FIELD_STEAM_RATING, FIELD_STAR_RATING):
        new_tag = replacement_tags.get(field)
        if new_tag is not None:
            updated.append(new_tag)

    return updated
