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


def test_download_job_handles_empty_queue_and_preserves_update_destinations():
    assert jobs.do_metadata_download([], 50, 1) == {}
    original = jobs.get_romanceio_fields_for_book
    calls = []

    def fetch(book_id, fields, max_tags, prefer_html, live_log=False):
        assert live_log
        calls.append(book_id)
        return {cfg.FIELD_STAR_RATING: 4.5} if book_id == "valid" else {}

    jobs.get_romanceio_fields_for_book = fetch
    try:
        results = jobs.do_metadata_download(
            [
                (1, "valid", [cfg.FIELD_STAR_RATING], [cfg.FIELD_STAR_RATING], []),
                (2, "failed", [cfg.FIELD_STAR_RATING], [cfg.FIELD_STAR_RATING], []),
            ],
            50,
            1,
        )
        assert calls == ["valid", "failed"]
        assert results[1][jobs.INTERNAL_CUSTOM_FIELDS_TO_UPDATE] == [cfg.FIELD_STAR_RATING]
        assert results[2] == {}
    finally:
        jobs.get_romanceio_fields_for_book = original


if __name__ == "__main__":
    test_download_job_handles_empty_queue_and_preserves_update_destinations()
    test_duplicate_destination_columns_are_rejected()
    test_category_columns_are_complete_and_empty_groups_are_clearable()
    print("All field-building tests passed!")
