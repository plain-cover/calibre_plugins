"""Tests for mapping parsed Romance.io values to configured calibre fields."""

from unittest.mock import patch

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


def test_download_job_stops_once_romanceio_asks_for_verification():
    original = jobs.get_romanceio_fields_for_book
    calls = []

    def fetch(book_id, fields, max_tags, prefer_html, live_log=False):
        calls.append(book_id)
        if book_id == "valid":
            return {cfg.FIELD_STAR_RATING: 4.5}
        return {jobs.INTERNAL_VERIFICATION_NEEDED: True}

    jobs.get_romanceio_fields_for_book = fetch
    try:
        results = jobs.do_metadata_download(
            [(book_id, romanceio_id, [], [], []) for book_id, romanceio_id in enumerate(["valid", "a", "b"], 1)],
            50,
            1,
        )
        assert calls == ["valid", "a"]
        assert results[2] == {}
        assert 3 not in results
    finally:
        jobs.get_romanceio_fields_for_book = original


def test_retry_job_log_starts_with_the_verification_log():
    import contextlib
    import io

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        jobs.do_metadata_download([], 50, 1, False, ["Opening Romance.io in Chrome"])
    assert output.getvalue().startswith(
        "Romance.io access was verified before this retry:\n[Verification] Opening Romance.io in Chrome\n"
    )


def test_failed_lookup_reports_that_verification_is_needed():
    def blocked(log_func, **_kwargs):
        log_func(jobs.VERIFY_HINT)
        return None

    with (
        patch(
            "calibre_plugins.romanceio_fields.common_romanceio_search_orchestrator.fetch_details_with_fallback", blocked
        ),
        patch("calibre_plugins.romanceio_fields.common_romanceio_fetch_helper.log_system_info"),
    ):
        result = jobs.get_romanceio_fields_for_book("id", [], 50)
    assert result == {
        jobs.INTERNAL_VERIFICATION_NEEDED: True,
        "__log__": [jobs.VERIFY_HINT, "Failed to fetch data for id"],
    }


def test_preparation_marks_only_books_the_check_blocked_for_retry():
    from types import SimpleNamespace

    titles = {1: "Missing", 2: "Blocked", 3: "Later"}
    db = SimpleNamespace(
        field_metadata=SimpleNamespace(key_to_label=lambda key: key),
        tags=lambda *_args, **_kwargs: "",
        get_custom=lambda *_args, **_kwargs: None,
        get_identifiers=lambda *_args, **_kwargs: {},
        title=lambda book_id, **_kwargs: titles[book_id],
        authors=lambda *_args, **_kwargs: "Author",
    )
    searched = []

    def search(title, _authors, _json_search, _html_search, log_func):
        searched.append(title)
        if title == "Blocked":
            log_func(jobs.VERIFY_HINT)
            raise RuntimeError("Search could not finish")
        return None  # Romance.io does not have this book

    with (
        patch("calibre.library.db", lambda _path: db),
        patch("calibre_plugins.romanceio_fields.common_romanceio_search_orchestrator.search_with_fallback", search),
    ):
        _books, warnings, errors, _saved = jobs.prepare_books_for_download([1, 2, 3], {}, [], True, "library")
    assert searched == ["Missing", "Blocked"]
    # Only the blocked and unsearched books are offered for retry after verification.
    assert warnings[1].startswith("Could not find Romance.io ID")
    assert warnings[2] == jobs.BLOCKED_BY_VERIFICATION
    assert warnings[3] == jobs.NOT_SEARCHED_PENDING_VERIFICATION
    assert {book_id for book_id, warning in warnings.items() if warning in jobs.PENDING_VERIFICATION_WARNINGS} == {2, 3}
    assert not errors


if __name__ == "__main__":
    test_download_job_handles_empty_queue_and_preserves_update_destinations()
    test_download_job_stops_once_romanceio_asks_for_verification()
    test_retry_job_log_starts_with_the_verification_log()
    test_failed_lookup_reports_that_verification_is_needed()
    test_preparation_marks_only_books_the_check_blocked_for_retry()
    test_duplicate_destination_columns_are_rejected()
    test_category_columns_are_complete_and_empty_groups_are_clearable()
    print("All field-building tests passed!")
