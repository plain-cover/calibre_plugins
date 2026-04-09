"""
Tests for common_romanceio_tag_mappings: slug-to-display-name conversion.

This file is shared by both plugins - it is copied to each plugin directory
during build, exactly like test_json_search_matching.py.

To run directly:
    python common/test_tag_slug_conversion.py

To run from a plugin directory after build:
    calibre-debug -e test_tag_slug_conversion.py
"""

import os
import sys

# Ensure the workspace root is on the path so 'from common.X import ...' works
# whether this file is run from common/ or from a plugin directory after build.
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from common.common_romanceio_tag_mappings import (  # pylint: disable=import-error
    JSON_TO_UI_TAG_MAP,
    TAGS_TO_IGNORE,
    convert_json_tags_to_display_names,
)


def test_convert_known_slugs():
    """Known JSON slugs should be converted to their UI display names."""
    print("=" * 60)
    print("Testing convert_json_tags_to_display_names - known slugs")
    print("=" * 60)

    cases = [
        ("from hate to love", "enemies to lovers"),
        ("dark", "dark romance"),
        ("f-f", "lesbian romance"),
        ("m-m", "gay romance"),
        ("humor", "funny"),
        ("fated-mates", "fated mates"),
    ]

    for slug, expected in cases:
        result = convert_json_tags_to_display_names([slug])
        assert result == [expected], f"'{slug}' -> expected '{expected}', got {result}"
        print(f"✓ '{slug}' -> '{expected}'")

    print()
    return True


def test_ignored_tags_removed():
    """Slugs in TAGS_TO_IGNORE must be filtered out entirely."""
    print("=" * 60)
    print("Testing ignored tags are removed")
    print("=" * 60)

    for slug in TAGS_TO_IGNORE:
        result = convert_json_tags_to_display_names([slug])
        assert not result, f"Ignored slug '{slug}' should be removed, got {result}"

    print(f"✓ All {len(TAGS_TO_IGNORE)} ignored slugs removed")
    print()
    return True


def test_unknown_slugs_pass_through():
    """Slugs absent from the map are kept as-is rather than dropped."""
    print("=" * 60)
    print("Testing unknown slugs pass through")
    print("=" * 60)

    slug = "some-future-tag"
    result = convert_json_tags_to_display_names([slug])
    assert result == [slug], f"Unknown slug should pass through, got {result}"
    print(f"✓ '{slug}' kept as-is")
    print()
    return True


def test_mixed_input():
    """A realistic mix of known, ignored, and unknown slugs."""
    print("=" * 60)
    print("Testing mixed input")
    print("=" * 60)

    inputs = ["from hate to love", "length-short", "fated-mates", "standalone-first", "some-new-tag"]
    result = convert_json_tags_to_display_names(inputs)

    assert "enemies to lovers" in result
    assert "fated mates" in result
    assert "some-new-tag" in result
    assert "length-short" not in result, "'length-short' is ignored"
    assert "Short: 150-249" not in result, "Ignored slug must not appear as mapped value"
    assert "standalone-first" not in result, "'standalone-first' is ignored"

    print(f"✓ {inputs} -> {result}")
    print()
    return True


def test_map_data_integrity():
    """Sanity checks on the map/ignore data: no empty keys/values.

    Multiple slugs may legitimately map to the same display name (e.g. both
    'sweet hero' and 'sweet-hero' -> 'sweet/gentle hero'), so duplicate values
    are intentionally allowed.
    """
    print("=" * 60)
    print("Testing map data integrity")
    print("=" * 60)

    assert len(JSON_TO_UI_TAG_MAP) > 0, "Map should not be empty"
    assert len(TAGS_TO_IGNORE) > 0, "Ignore set should not be empty"

    for key, value in JSON_TO_UI_TAG_MAP.items():
        assert key and isinstance(key, str), f"Empty/non-string key in map: {key!r}"
        assert value and isinstance(value, str), f"Empty/non-string value for key {key!r}: {value!r}"

    # Overlap between map and ignore set is noted, not an error (ignore takes priority)
    overlap = TAGS_TO_IGNORE & set(JSON_TO_UI_TAG_MAP.keys())
    if overlap:
        print(f"  Note: {len(overlap)} slugs in both map and ignore set (ignore takes priority): {sorted(overlap)}")
    else:
        print("✓ No overlap between ignore set and map keys")

    print(f"✓ Map has {len(JSON_TO_UI_TAG_MAP)} entries, ignore set has {len(TAGS_TO_IGNORE)} entries")
    print()
    return True


if __name__ == "__main__":
    print("Starting tag slug conversion tests (common)...\n")

    ALL_PASSED = True
    ALL_PASSED &= test_convert_known_slugs()
    ALL_PASSED &= test_ignored_tags_removed()
    ALL_PASSED &= test_unknown_slugs_pass_through()
    ALL_PASSED &= test_mixed_input()
    ALL_PASSED &= test_map_data_integrity()

    print("=" * 60)
    if ALL_PASSED:
        print("All tag slug conversion tests passed!")
    else:
        print("Some tests FAILED - see output above")
    print("=" * 60)

    sys.exit(0 if ALL_PASSED else 1)
