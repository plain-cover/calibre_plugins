"""Tests for mirroring fetched ratings into calibre's standard Tags field."""

import os
import sys

plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.test_data import load_plugin_module

rating_tags = load_plugin_module("romanceio_fields.rating_tags", "rating_tags.py", plugin_dir)
FIELD_STAR_RATING = rating_tags.FIELD_STAR_RATING
FIELD_STEAM_RATING = rating_tags.FIELD_STEAM_RATING
build_field_update_plan = rating_tags.build_field_update_plan
format_rating_tag = rating_tags.format_rating_tag
has_rating_tag = rating_tags.has_rating_tag
normalize_calibre_tags = rating_tags.normalize_calibre_tags
reconcile_rating_tags = rating_tags.reconcile_rating_tags


def test_normalize_calibre_tags_supports_legacy_and_new_api_values():
    assert normalize_calibre_tags("Romance, Fantasy") == ["Romance", "Fantasy"]
    assert normalize_calibre_tags(("Romance", "Fantasy")) == ["Romance", "Fantasy"]
    assert normalize_calibre_tags(None) == []


def test_format_rating_tags():
    assert format_rating_tag(FIELD_STEAM_RATING, 3) == "Romance.io steam: 3/5"
    assert format_rating_tag(FIELD_STAR_RATING, 4.25) == "Romance.io stars: 4.25/5"
    assert format_rating_tag(FIELD_STAR_RATING, 4.0) == "Romance.io stars: 4/5"
    assert format_rating_tag(FIELD_STEAM_RATING, None) is None


def test_has_rating_tag_is_case_insensitive():
    tags = ["Romance", "ROMANCE.IO STEAM: 2/5"]
    assert has_rating_tag(tags, FIELD_STEAM_RATING)
    assert not has_rating_tag(tags, FIELD_STAR_RATING)


def test_reconcile_replaces_owned_tags_and_preserves_other_tags():
    existing = [
        "Romance",
        "Romance.io steam: 2/5",
        "Favorites",
        "Romance.io stars: 4.1/5",
    ]
    values = {FIELD_STEAM_RATING: 3, FIELD_STAR_RATING: 4.25}

    updated = reconcile_rating_tags(
        existing,
        values,
        {FIELD_STEAM_RATING, FIELD_STAR_RATING},
    )

    assert updated == [
        "Romance",
        "Favorites",
        "Romance.io steam: 3/5",
        "Romance.io stars: 4.25/5",
    ]


def test_reconcile_only_changes_selected_rating_type():
    existing = ["Romance.io steam: 2/5", "Romance.io stars: 4.1/5"]
    updated = reconcile_rating_tags(
        existing,
        {FIELD_STEAM_RATING: 3},
        {FIELD_STEAM_RATING},
    )
    assert updated == ["Romance.io stars: 4.1/5", "Romance.io steam: 3/5"]


def test_reconcile_removes_stale_tag_when_successful_rating_is_empty():
    existing = ["Romance", "Romance.io steam: 2/5"]
    updated = reconcile_rating_tags(
        existing,
        {FIELD_STEAM_RATING: None},
        {FIELD_STEAM_RATING},
    )
    assert updated == ["Romance"]


def test_reconcile_is_idempotent():
    values = {FIELD_STEAM_RATING: 3, FIELD_STAR_RATING: 4.25}
    fields = {FIELD_STEAM_RATING, FIELD_STAR_RATING}
    first = reconcile_rating_tags(["Romance"], values, fields)
    second = reconcile_rating_tags(first, values, fields)
    assert second == first


def test_update_plan_supports_tag_only_configuration():
    fields_to_run, custom_fields, tag_fields = build_field_update_plan(
        {FIELD_STEAM_RATING: "", FIELD_STAR_RATING: ""},
        {FIELD_STEAM_RATING},
        True,
        {},
        ["Romance"],
    )
    assert fields_to_run == [FIELD_STEAM_RATING]
    assert custom_fields == []
    assert tag_fields == [FIELD_STEAM_RATING]


def test_update_plan_does_not_overwrite_custom_column_when_only_tag_is_missing():
    fields_to_run, custom_fields, tag_fields = build_field_update_plan(
        {FIELD_STEAM_RATING: "#steam"},
        {FIELD_STEAM_RATING},
        False,
        {FIELD_STEAM_RATING: 2},
        ["Romance"],
    )
    assert fields_to_run == [FIELD_STEAM_RATING]
    assert custom_fields == []
    assert tag_fields == [FIELD_STEAM_RATING]


def test_update_plan_skips_populated_destinations_when_refresh_is_off():
    fields_to_run, custom_fields, tag_fields = build_field_update_plan(
        {FIELD_STAR_RATING: "#stars"},
        {FIELD_STAR_RATING},
        False,
        {FIELD_STAR_RATING: 4.1},
        ["Romance.io stars: 4.1/5"],
    )
    assert fields_to_run == []
    assert custom_fields == []
    assert tag_fields == []


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"All {len(tests)} rating tag tests passed")
