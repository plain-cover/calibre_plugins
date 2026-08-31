"""Tests for mapping parsed Romance.io values to configured calibre fields."""

from test_utils import setup_test_environment  # type: ignore[import-not-found]  # pylint: disable=import-error

env = setup_test_environment("romanceio_fields")
cfg = env["config_module"]
jobs = env["load_plugin_module"]("romanceio_fields.jobs", "jobs.py", env["plugin_dir"])


def test_duplicate_destination_columns_are_rejected():
    duplicates = cfg.find_duplicate_column_mappings(
        {
            cfg.FIELD_ROMANCE_TAGS: "#tags",
            cfg.FIELD_GENERAL_TAGS: "#tags",
            cfg.FIELD_STAR_RATING: "#stars",
            cfg.FIELD_STEAM_RATING: "",
        }
    )
    assert duplicates == {"#tags": [cfg.FIELD_ROMANCE_TAGS, cfg.FIELD_GENERAL_TAGS]}


def test_category_columns_are_complete_and_empty_groups_are_clearable():
    parsed = {
        "tags": ["one", "two", "three"],
        "general_tags": ["one", "two", "three"],
        "content_warnings": [],
        "geography_tags": ["england"],
        "format_tags": ["Long: 400-599", "standalone or first in series"],
    }
    fields = [cfg.FIELD_ROMANCE_TAGS, *cfg.CATEGORY_FIELD_TO_PARSED_KEY]
    result = jobs._build_fields(parsed, fields, max_tags=1)  # pylint: disable=protected-access

    assert result[cfg.FIELD_ROMANCE_TAGS] == "one"
    assert result[cfg.FIELD_GENERAL_TAGS] == "one,two,three"
    assert result[cfg.FIELD_CONTENT_WARNINGS] == ""
    assert result[cfg.FIELD_GEOGRAPHY] == "england"
    assert result[cfg.FIELD_FORMAT_TAGS] == "Long: 400-599,standalone or first in series"


if __name__ == "__main__":
    test_duplicate_destination_columns_are_rejected()
    test_category_columns_are_complete_and_empty_groups_are_clearable()
    print("All field-building tests passed!")
