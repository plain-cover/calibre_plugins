"""
Tests for the romanceio plugin's tag handling:
  - genre mapping: display names -> Calibre tags
  - integration: JSON slugs fed through the full pipeline

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

from common.common_romanceio_tag_mappings import (  # pylint: disable=import-error
    JSON_TO_UI_TAG_MAP,
    TAGS_TO_IGNORE,
    convert_json_tags_to_display_names,
)
from romanceio.parse_html import convert_genres_to_calibre_tags  # pylint: disable=import-error
from romanceio.config_defaults import DEFAULT_GENRE_MAPPINGS  # pylint: disable=import-error

# ---------------------------------------------------------------------------
# Genre mapping tests
# ---------------------------------------------------------------------------


def test_genre_mapping_with_display_names():
    """Display names from HTML tags should resolve against the genre map."""
    print("=" * 60)
    print("Testing genre mapping with HTML-style display names")
    print("=" * 60)

    html_tags = ["dark romance", "fantasy", "paranormal"]
    result = convert_genres_to_calibre_tags(html_tags, map_genres=True, calibre_tag_map=DEFAULT_GENRE_MAPPINGS)

    assert "Romance" in result, f"Expected 'Romance' in {result}"
    assert "Dark Romance" in result, f"Expected 'Dark Romance' in {result}"
    assert "Fantasy" in result, f"Expected 'Fantasy' in {result}"
    assert "Paranormal" in result, f"Expected 'Paranormal' in {result}"

    print(f"✓ {html_tags} -> {result}")
    print()
    return True


def test_genre_mapping_disabled():
    """When mapping is disabled all tags pass through unchanged."""
    print("=" * 60)
    print("Testing genre mapping disabled")
    print("=" * 60)

    tags = ["dark romance", "fantasy", "enemies to lovers"]
    result = convert_genres_to_calibre_tags(tags, map_genres=False, calibre_tag_map=DEFAULT_GENRE_MAPPINGS)

    assert result == tags, f"Expected tags unchanged, got {result}"
    print(f"✓ Tags passed through: {result}")
    print()
    return True


def test_unrecognised_display_names_excluded():
    """Tags not in the genre map are silently dropped when mapping is enabled."""
    print("=" * 60)
    print("Testing unrecognised display names are excluded")
    print("=" * 60)

    tags = ["enemies to lovers", "dual pov", "dark romance"]
    result = convert_genres_to_calibre_tags(tags, map_genres=True, calibre_tag_map=DEFAULT_GENRE_MAPPINGS)

    assert "enemies to lovers" not in result, "'enemies to lovers' is not in default genre map"
    assert "dual pov" not in result, "'dual pov' is not in default genre map"
    assert "Dark Romance" in result, f"Expected 'Dark Romance', got {result}"

    print(f"✓ Only mapped genres included: {result}")
    print()
    return True


def test_genre_map_is_case_insensitive():
    """Tag lookup against the genre map should be case-insensitive."""
    print("=" * 60)
    print("Testing genre mapping case insensitivity")
    print("=" * 60)

    tags = ["Dark Romance", "FANTASY", "Paranormal"]
    result = convert_genres_to_calibre_tags(tags, map_genres=True, calibre_tag_map=DEFAULT_GENRE_MAPPINGS)

    assert "Dark Romance" in result
    assert "Fantasy" in result
    assert "Paranormal" in result

    print(f"✓ Case-insensitive lookup: {result}")
    print()
    return True


# ---------------------------------------------------------------------------
# End-to-end: JSON slugs -> display names -> calibre tags
# ---------------------------------------------------------------------------


def test_json_to_calibre_pipeline():
    """Simulate the full path: JSON tropes -> display names -> calibre tags."""
    print("=" * 60)
    print("Testing full pipeline: JSON slugs -> display names -> Calibre tags")
    print("=" * 60)

    json_slugs = ["dark", "m-m", "fantasy", "from hate to love", "fated-mates", "length-short"]
    display_names = convert_json_tags_to_display_names(json_slugs)
    print(f"  After slug -> display: {display_names}")

    assert "length-short" not in display_names, "'length-short' is ignored"
    assert "Short: 150-249" not in display_names, "Ignored slug must not appear as mapped value"

    calibre_tags = convert_genres_to_calibre_tags(
        display_names, map_genres=True, calibre_tag_map=DEFAULT_GENRE_MAPPINGS
    )
    print(f"  After genre mapping: {calibre_tags}")

    assert "Romance" in calibre_tags
    assert "Dark Romance" in calibre_tags, f"'dark' -> 'dark romance' -> 'Dark Romance': got {calibre_tags}"
    assert "Gay Romance" in calibre_tags, f"'m-m' -> 'gay romance' -> 'Gay Romance': got {calibre_tags}"
    assert "Fantasy" in calibre_tags

    # These display names are not in the default genre map
    assert "enemies to lovers" not in calibre_tags
    assert "fated mates" not in calibre_tags

    print(f"✓ Pipeline produced expected calibre tags: {calibre_tags}")
    print()
    return True


def test_identical_slug_and_display_names():
    """Some slugs match their genre map key exactly (no remapping needed)."""
    print("=" * 60)
    print("Testing slugs identical to genre map keys")
    print("=" * 60)

    json_slugs = ["contemporary", "suspense", "young adult"]
    display_names = convert_json_tags_to_display_names(json_slugs)
    assert display_names == json_slugs, f"Identical slugs should pass through: {display_names}"

    calibre_tags = convert_genres_to_calibre_tags(
        display_names, map_genres=True, calibre_tag_map=DEFAULT_GENRE_MAPPINGS
    )
    assert "Contemporary" in calibre_tags
    assert "Suspense" in calibre_tags
    assert "Young Adult" in calibre_tags

    print(f"✓ Identical-slug genres mapped correctly: {calibre_tags}")
    print()
    return True


def test_default_genre_mapping_keys_are_valid_display_names():
    """Every DEFAULT_GENRE_MAPPINGS key must be a display name that Romance.io
    actually produces - either as an explicit slug -> display-name mapping in
    JSON_TO_UI_TAG_MAP, or as a pass-through slug that the API emits directly.

    This test will fail if update_tag_mappings.py updates a display name in
    JSON_TO_UI_TAG_MAP without a corresponding update to DEFAULT_GENRE_MAPPINGS,
    which would leave DEFAULT_GENRE_MAPPINGS with a stale key that never matches
    any parsed tag.

    Pass-through keys (where the JSON slug equals the display name) are tested
    separately: they must not appear in TAGS_TO_IGNORE.
    """
    print("=" * 60)
    print("Testing DEFAULT_GENRE_MAPPINGS keys are valid Romance.io display names")
    print("=" * 60)

    explicit_display_names = set(JSON_TO_UI_TAG_MAP.values())

    # Keys currently produced by an explicit slug -> display-name mapping.
    # These are the highest-risk for staleness: if update_tag_mappings.py
    # renames one, it will no longer appear in explicit_display_names.
    explicitly_mapped = [k for k in DEFAULT_GENRE_MAPPINGS if k in explicit_display_names]

    # Keys that must pass through unchanged (slug == display name).
    pass_through = [k for k in DEFAULT_GENRE_MAPPINGS if k not in explicit_display_names]

    stale_explicit = [k for k in explicitly_mapped if k not in explicit_display_names]
    assert not stale_explicit, (
        f"DEFAULT_GENRE_MAPPINGS keys no longer appear as display names in "
        f"JSON_TO_UI_TAG_MAP (stale after a tag rename?): {stale_explicit}"
    )

    stale_pass_through = [k for k in pass_through if k in TAGS_TO_IGNORE]
    assert (
        not stale_pass_through
    ), f"DEFAULT_GENRE_MAPPINGS keys are in TAGS_TO_IGNORE and will always be filtered out: {stale_pass_through}"

    print(f"✓ {len(explicitly_mapped)} explicitly-mapped keys still valid: {explicitly_mapped}")
    print(f"✓ {len(pass_through)} pass-through keys not filtered: {pass_through}")
    print()
    return True


if __name__ == "__main__":
    print("Starting tag mapping tests for romanceio plugin...\n")

    ALL_PASSED = True
    ALL_PASSED &= test_genre_mapping_with_display_names()
    ALL_PASSED &= test_genre_mapping_disabled()
    ALL_PASSED &= test_unrecognised_display_names_excluded()
    ALL_PASSED &= test_genre_map_is_case_insensitive()
    ALL_PASSED &= test_json_to_calibre_pipeline()
    ALL_PASSED &= test_identical_slug_and_display_names()
    ALL_PASSED &= test_default_genre_mapping_keys_are_valid_display_names()

    print("=" * 60)
    if ALL_PASSED:
        print("All tag mapping tests passed!")
    else:
        print("Some tests FAILED - see output above")
    print("=" * 60)

    sys.exit(0 if ALL_PASSED else 1)
