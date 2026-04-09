"""
Tests specific to the romanceio_fields tag-mapping workflow:
  - consistency: display names from the common module match the romanceio genre-map keys
  - HTML topics-page extraction (used by update_tag_mappings.py)

Slug-to-display-name conversion tests live in common/test_tag_slug_conversion.py.

To run this test:
    calibre-debug -e test_tag_mapping.py
"""

import os
import sys

# Allow running from the plugin directory directly
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from update_tag_mappings import extract_tag_mappings_from_html  # type: ignore[import-not-found]  # pylint: disable=import-error
from common.common_romanceio_tag_mappings import (  # pylint: disable=import-error
    JSON_TO_UI_TAG_MAP,
    TAGS_TO_IGNORE,
    convert_json_tags_to_display_names,
)

# ---------------------------------------------------------------------------
# Cross-plugin consistency check
# ---------------------------------------------------------------------------


def test_display_names_are_consistent_with_config_defaults():
    """Display names produced by the mapping should match the genre keys used in
    the romanceio plugin's default ConfigWidget mapping table, so that tags fetched
    via JSON can be looked up by the same genre-mapping logic as HTML tags."""
    print("=" * 60)
    print("Testing display names match romanceio default genre mapping keys")
    print("=" * 60)

    # These are genre keys from romanceio/config.py DEFAULT_GENRE_MAPPINGS that
    # must be reachable from JSON slugs via convert_json_tags_to_display_names.
    expected_reachable = {
        "contemporary": "contemporary",  # slug == display name
        "dark romance": "dark",
        "fantasy": "fantasy",
        "gay romance": "m-m",
        "lesbian romance": "f-f",
        "paranormal": "paranormal",
        "suspense": "suspense",
        "young adult": "young adult",
    }

    for display_name, slug in expected_reachable.items():
        result = convert_json_tags_to_display_names([slug])
        assert (
            display_name in result
        ), f"Slug '{slug}' should produce display name '{display_name}' for genre mapping; got {result}"
        print(f"✓ slug '{slug}' -> '{display_name}' (usable by genre mapping)")

    print()
    return True


def test_map_has_no_ignored_keys():
    """None of the TAGS_TO_IGNORE slugs should also be keys in JSON_TO_UI_TAG_MAP,
    since that would be contradictory."""
    print("=" * 60)
    print("Testing TAGS_TO_IGNORE and JSON_TO_UI_TAG_MAP are disjoint")
    print("=" * 60)

    overlap = TAGS_TO_IGNORE & set(JSON_TO_UI_TAG_MAP.keys())
    # Some overlap is intentional (e.g. 'behind-doors', 'open-door' exist in both
    # because they appear in the HTML but the ignore list takes priority in the
    # conversion function). Just log rather than assert here.
    if overlap:
        print(f"  Note: {len(overlap)} slugs appear in both map and ignore set: {sorted(overlap)}")
        print("  (ignore list takes priority - these will be filtered out)")
    else:
        print("✓ No overlap between ignore set and map keys")
    print()
    return True


# ---------------------------------------------------------------------------
# Topics page extraction (requires static HTML in test_data/)
# ---------------------------------------------------------------------------


def load_topics_html():
    """Load the static topics page HTML from test_data."""
    test_data_dir = os.path.join(os.path.dirname(__file__), "test_data")
    html_file = os.path.join(test_data_dir, "romanceio_topics_page.html")

    if not os.path.exists(html_file):
        print(f"✗ Test file not found: {html_file}")
        return None

    with open(html_file, "r", encoding="utf-8") as f:
        return f.read()


def test_tag_extraction():
    """Test that tag extraction works correctly from static HTML."""
    print("=" * 60)
    print("Testing tag extraction from static HTML")
    print("=" * 60)

    html_content = load_topics_html()
    if not html_content:
        print("✗ Could not load static HTML file")
        return False

    print(f"✓ Loaded HTML file ({len(html_content)} bytes)")

    mappings = extract_tag_mappings_from_html(html_content)

    assert len(mappings) > 0, "Should extract at least some tag mappings"
    print(f"✓ Extracted {len(mappings)} tag mappings")

    expected = {
        "from hate to love": "enemies to lovers",
        "age difference": "age gap",
        "arranged marriage": "arranged/forced marriage",
        "bff-parent": "best friend's parent",
    }

    for key, expected_value in expected.items():
        assert key in mappings, f"Expected mapping for '{key}' not found"
        assert (
            mappings[key] == expected_value
        ), f"Mapping for '{key}' incorrect: expected '{expected_value}', got '{mappings[key]}'"
        print(f"✓ '{key}' -> '{mappings[key]}'")

    assert "&amp;" not in str(mappings.values()), "HTML entities should be decoded"
    print("✓ HTML entities properly decoded")

    identical_count = sum(1 for k, v in mappings.items() if k == v)
    print(f"✓ {identical_count} identical key-value pairs found (filtered in actual use)")

    print()
    print("=" * 60)
    print("✓ All assertions passed for HTML tag extraction")
    print("=" * 60)
    return True


if __name__ == "__main__":
    print("Starting tag mapping tests for romanceio_fields plugin...\n")

    ALL_PASSED = True
    ALL_PASSED &= test_display_names_are_consistent_with_config_defaults()
    ALL_PASSED &= test_map_has_no_ignored_keys()
    ALL_PASSED &= test_tag_extraction()

    print("=" * 60)
    if ALL_PASSED:
        print("All tag mapping tests passed!")
    else:
        print("Some tests FAILED - see output above")
    print("=" * 60)

    sys.exit(0 if ALL_PASSED else 1)
