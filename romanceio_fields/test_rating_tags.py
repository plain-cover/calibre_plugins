"""Tests for mirroring fetched ratings into calibre's standard Tags field."""

import builtins
import os
import sys
import types

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
is_owned_rating_tag = rating_tags.is_owned_rating_tag
normalize_calibre_tags = rating_tags.normalize_calibre_tags
reconcile_rating_tags = rating_tags.reconcile_rating_tags


def _module(name, **attributes):
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


def _load_action_module():
    """Load action.py with small stubs so its database bridge can be tested offline."""

    class DummyToolButton:
        MenuButtonPopup = object()

    class DummyParallelJob:
        def __init__(self, *args, **kwargs):
            pass

    package = _module("romanceio_fields")
    package.__path__ = [plugin_dir]

    _module("qt")
    _module("qt.core", QToolButton=DummyToolButton, QMenu=object, QObject=object)
    _module(
        "calibre.gui2",
        error_dialog=lambda *args, **kwargs: None,
        question_dialog=lambda *args, **kwargs: False,
    )
    _module("calibre.gui2.actions", InterfaceAction=object)
    _module("calibre.gui2.dialogs")
    _module("calibre.gui2.dialogs.message_box", ErrorNotification=object)
    _module("calibre.utils")
    _module("calibre.utils.ipc")
    _module("calibre.utils.ipc.job", ParallelJob=DummyParallelJob)

    config = _module(
        "romanceio_fields.config",
        ALL_FIELDS={},
        ID_NAME="romanceio",
    )
    _module(
        "romanceio_fields.common_icons",
        set_plugin_icon_resources=lambda *args, **kwargs: None,
        get_icon=lambda *args, **kwargs: None,
    )
    _module(
        "romanceio_fields.common_menus",
        unregister_menu_actions=lambda *args, **kwargs: None,
        create_menu_action_unique=lambda *args, **kwargs: None,
    )
    _module("romanceio_fields.common_dialogs", ProgressBarDialog=object)
    _module(
        "romanceio_fields.jobs",
        INTERNAL_CUSTOM_FIELDS_TO_UPDATE="__custom_fields_to_update__",
        INTERNAL_TAG_FIELDS_TO_UPDATE="__tag_fields_to_update__",
        call_plugin_callback=lambda *args, **kwargs: None,
    )
    sys.modules["romanceio_fields.rating_tags"] = rating_tags

    previous_translation = getattr(builtins, "_", None)
    builtins._ = lambda value: value  # type: ignore[attr-defined]
    try:
        action_module = load_plugin_module("romanceio_fields.action", "action.py", plugin_dir)
    finally:
        if previous_translation is None:
            del builtins._  # type: ignore[attr-defined]
        else:
            builtins._ = previous_translation  # type: ignore[attr-defined]

    action_module.cfg = config  # type: ignore[attr-defined]
    return action_module


def test_normalize_calibre_tags_supports_legacy_and_new_api_values():
    assert normalize_calibre_tags("Romance, Fantasy") == ["Romance", "Fantasy"]
    assert normalize_calibre_tags(("Romance", "Fantasy")) == ["Romance", "Fantasy"]
    assert normalize_calibre_tags(None) == []


def test_format_rating_tags():
    assert format_rating_tag(FIELD_STEAM_RATING, 3) == "Romance.io steam: 3"
    assert format_rating_tag(FIELD_STAR_RATING, 4.25) == "Romance.io stars: 4.3"
    assert format_rating_tag(FIELD_STAR_RATING, 4.0) == "Romance.io stars: 4.0"
    assert format_rating_tag(FIELD_STEAM_RATING, None) is None


def test_format_rating_tags_rejects_invalid_remote_values():
    invalid_values = ("not-a-number", float("nan"), float("inf"), -1, 6)
    for value in invalid_values:
        assert format_rating_tag(FIELD_STAR_RATING, value) is None
        assert format_rating_tag(FIELD_STEAM_RATING, value) is None


def test_owned_rating_tag_matching_is_strict_case_insensitive_and_supports_legacy_tags():
    assert is_owned_rating_tag("ROMANCE.IO STEAM: 2/5", FIELD_STEAM_RATING)
    assert is_owned_rating_tag("Romance.io steam: 3", FIELD_STEAM_RATING)
    assert is_owned_rating_tag("Romance.io stars: 4.25/5", FIELD_STAR_RATING)
    assert is_owned_rating_tag("Romance.io stars: 4.3", FIELD_STAR_RATING)
    assert not is_owned_rating_tag("Romance.io steam: favorites", FIELD_STEAM_RATING)
    assert not is_owned_rating_tag("Romance.io stars: someday", FIELD_STAR_RATING)
    assert not is_owned_rating_tag("Romance.io steam: 6", FIELD_STEAM_RATING)


def test_has_rating_tag_ignores_unrelated_prefix_sharing_tags():
    tags = ["Romance", "ROMANCE.IO STEAM: 2/5", "Romance.io stars: someday"]
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
        "Romance.io steam: 3",
        "Romance.io stars: 4.3",
    ]


def test_reconcile_only_changes_selected_rating_type():
    existing = ["Romance.io steam: 2/5", "Romance.io stars: 4.1/5"]
    updated = reconcile_rating_tags(
        existing,
        {FIELD_STEAM_RATING: 3},
        {FIELD_STEAM_RATING},
    )
    assert updated == ["Romance.io stars: 4.1/5", "Romance.io steam: 3"]


def test_reconcile_preserves_unrelated_prefix_sharing_tags():
    existing = ["Romance.io steam: favorites", "Romance.io stars: someday"]
    updated = reconcile_rating_tags(
        existing,
        {FIELD_STEAM_RATING: 3, FIELD_STAR_RATING: 4.25},
        {FIELD_STEAM_RATING, FIELD_STAR_RATING},
    )
    assert updated == [
        "Romance.io steam: favorites",
        "Romance.io stars: someday",
        "Romance.io steam: 3",
        "Romance.io stars: 4.3",
    ]


def test_reconcile_preserves_existing_rating_when_remote_value_is_invalid_or_missing():
    existing = ["Romance.io steam: 2/5", "Romance.io stars: 4.1/5"]
    updated = reconcile_rating_tags(
        existing,
        {FIELD_STEAM_RATING: float("inf")},
        {FIELD_STEAM_RATING, FIELD_STAR_RATING},
    )
    assert updated == existing


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


def test_database_bridge_applies_planned_tag_update_and_recounts():
    action_module = _load_action_module()

    class FakeNewApi:
        def __init__(self):
            self.tags = {
                1: [
                    "Romance",
                    "Romance.io steam: 2/5",
                    "Romance.io steam: favorites",
                ]
            }
            self.writes = []

        def has_id(self, book_id):
            return book_id in self.tags

        def field_for(self, field, book_id):
            if field == "title":
                return "Test Book"
            if field == "tags":
                return self.tags[book_id]
            raise AssertionError(f"Unexpected field read: {field}")

        def set_field(self, field, values):
            self.writes.append((field, values))
            if field == "tags":
                self.tags.update(values)

    class FakeModel:
        def refresh_ids(self, *args, **kwargs):
            pass

    class FakeIndex:
        @staticmethod
        def row():
            return 0

    class FakeLibraryView:
        def model(self):
            return FakeModel()

        def currentIndex(self):
            return FakeIndex()

    class FakeTagsView:
        def __init__(self):
            self.recount_calls = 0

        def recount(self):
            self.recount_calls += 1

    class FakeAction:
        def __init__(self):
            new_api = FakeNewApi()
            self.gui = types.SimpleNamespace(
                current_db=types.SimpleNamespace(new_api=new_api),
                library_view=FakeLibraryView(),
                tags_view=FakeTagsView(),
            )
            self.pb = None

        def progressbar(self, *args, **kwargs):
            pass

        def show_progressbar(self, *args, **kwargs):
            pass

        def set_progressbar_label(self, *args, **kwargs):
            pass

        def increment_progressbar(self):
            pass

        def hide_progressbar(self):
            pass

    fake_action = FakeAction()
    payload = (
        {FIELD_STEAM_RATING: ""},
        {FIELD_STEAM_RATING},
        {
            1: {
                FIELD_STEAM_RATING: 3,
                action_module.INTERNAL_CUSTOM_FIELDS_TO_UPDATE: [],
                action_module.INTERNAL_TAG_FIELDS_TO_UPDATE: [FIELD_STEAM_RATING],
            }
        },
    )

    previous_translation = getattr(builtins, "_", None)
    builtins._ = lambda value: value  # type: ignore[attr-defined]
    try:
        action_module.RomanceIOFieldsAction._update_database_columns(fake_action, payload)
    finally:
        if previous_translation is None:
            del builtins._  # type: ignore[attr-defined]
        else:
            builtins._ = previous_translation  # type: ignore[attr-defined]

    assert fake_action.gui.current_db.new_api.writes == [
        (
            "tags",
            {
                1: [
                    "Romance",
                    "Romance.io steam: favorites",
                    "Romance.io steam: 3",
                ]
            },
        )
    ]
    assert fake_action.gui.tags_view.recount_calls == 1


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"All {len(tests)} rating tag tests passed")
