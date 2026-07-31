"""Regression tests for the weekly Romance.io taxonomy maintenance check."""

import sys
from pathlib import Path

import pytest

from common import check_romanceio_tag_taxonomy
from common import update_tag_mappings
from common.check_romanceio_tag_taxonomy import _difference_lines, required_display_mappings


def test_checker_requires_an_explicit_input_mode(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_romanceio_tag_taxonomy.py"])

    with pytest.raises(SystemExit, match="2"):
        check_romanceio_tag_taxonomy.main()


def test_categorized_ignored_tag_still_requires_display_mapping():
    required = required_display_mappings(
        {"standalone-first": "standalone or first in series", "clean": "behind closed doors"},
        {"standalone-first", "clean"},
        {"standalone-first"},
    )
    assert required == {"standalone-first": "standalone or first in series"}


def test_strict_live_comparison_detects_truncated_taxonomy():
    lines = _difference_lines(
        live_categories={"kept": "format_tags"},
        live_display_names={},
        bundled_categories={"kept": "format_tags", "missing": "geography_tags"},
        bundled_display_names={},
        tags_to_ignore=set(),
        live_topic_count=300,
        bundled_topic_count=387,
        strict=True,
    )
    text = "\n".join(lines)
    assert "Categorized tags removed" in text
    assert "'missing': 'geography_tags'" in text
    assert "Topic-tag count changed: bundled=387, live=300" in text


def test_captured_fixture_comparison_allows_older_subset():
    lines = _difference_lines(
        live_categories={"kept": "format_tags"},
        live_display_names={},
        bundled_categories={"kept": "format_tags", "newer": "geography_tags"},
        bundled_display_names={},
        tags_to_ignore=set(),
        live_topic_count=300,
        bundled_topic_count=387,
        strict=False,
    )
    assert lines == []  # pylint: disable=use-implicit-booleaness-not-comparison


def test_strict_live_comparison_detects_mapping_that_became_identity():
    lines = _difference_lines(
        live_categories={},
        live_display_names={"humor": "humor"},
        bundled_categories={},
        bundled_display_names={"humor": "funny"},
        tags_to_ignore=set(),
        live_topic_count=1,
        bundled_topic_count=1,
        strict=True,
    )
    text = "\n".join(lines)
    assert "Obsolete slug-to-display-name mappings" in text
    assert "'humor': 'funny'" in text


def test_mapping_renderer_removes_values_absent_from_desired_taxonomy(tmp_path):
    mapping_file = tmp_path / "common_romanceio_tag_mappings.py"
    mapping_file.write_text(
        "# Last tag mapping update: 2026-01-01\n"
        "# Number of topic tags seen during the same update. This includes identity\n"
        "# mappings, which are intentionally omitted from JSON_TO_UI_TAG_MAP.\n"
        "TOPIC_TAG_COUNT = 1\n"
        'JSON_TO_UI_TAG_MAP = {\n    "humor": "funny",\n}\n',
        encoding="utf-8",
    )

    rendered = update_tag_mappings.render_tag_mapping_module(mapping_file, {}, 1)

    assert '"humor": "funny"' not in rendered
    assert "JSON_TO_UI_TAG_MAP = {\n}" in rendered


def test_mapping_renderer_escapes_unicode_and_punctuation_round_trip(tmp_path):
    mapping_file = tmp_path / "common_romanceio_tag_mappings.py"
    mapping_file.write_text(
        "# Last tag mapping update: 2026-01-01\n"
        "# Number of topic tags seen during the same update. This includes identity\n"
        "# mappings, which are intentionally omitted from JSON_TO_UI_TAG_MAP.\n"
        "TOPIC_TAG_COUNT = 1\n"
        "JSON_TO_UI_TAG_MAP = {}\n",
        encoding="utf-8",
    )
    mappings = {
        "reader's-choice": "Reader's choice — surprise, joy & tears!",
        'quoted-"tag"': 'A "quoted" title',
    }

    rendered = update_tag_mappings.render_tag_mapping_module(mapping_file, mappings, 2)
    compile(rendered, str(mapping_file), "exec")
    mapping_file.write_text(rendered, encoding="utf-8")

    assert update_tag_mappings.parse_existing_mappings(mapping_file) == mappings


def test_generated_files_are_unchanged_when_validation_fails(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("VALUE = 'old-first'\n", encoding="utf-8")
    second.write_text("VALUE = 'old-second'\n", encoding="utf-8")

    with pytest.raises(SyntaxError):
        update_tag_mappings._write_generated_files_transactionally(  # pylint: disable=protected-access
            {first: "VALUE = 'new-first'\n", second: "VALUE =\n"}
        )

    assert first.read_text(encoding="utf-8") == "VALUE = 'old-first'\n"
    assert second.read_text(encoding="utf-8") == "VALUE = 'old-second'\n"


def test_generated_files_roll_back_when_second_replace_fails(tmp_path, monkeypatch):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("VALUE = 'old-first'\n", encoding="utf-8")
    second.write_text("VALUE = 'old-second'\n", encoding="utf-8")
    real_replace = update_tag_mappings.os.replace

    def fail_second_new_file(source, destination):
        source_path = Path(source)
        if Path(destination) == second and ".new-" in source_path.name:
            raise OSError("simulated second replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(update_tag_mappings.os, "replace", fail_second_new_file)

    with pytest.raises(OSError, match="simulated second replacement failure"):
        update_tag_mappings._write_generated_files_transactionally(  # pylint: disable=protected-access
            {first: "VALUE = 'new-first'\n", second: "VALUE = 'new-second'\n"}
        )

    assert first.read_text(encoding="utf-8") == "VALUE = 'old-first'\n"
    assert second.read_text(encoding="utf-8") == "VALUE = 'old-second'\n"


def test_generated_files_preserve_backup_when_rollback_fails(tmp_path, monkeypatch):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("VALUE = 'old-first'\n", encoding="utf-8")
    second.write_text("VALUE = 'old-second'\n", encoding="utf-8")
    real_replace = update_tag_mappings.os.replace

    def fail_second_new_file_and_first_rollback(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path == second and ".new-" in source_path.name:
            raise OSError("simulated second replacement failure")
        if destination_path == first and ".backup-" in source_path.name:
            raise OSError("simulated rollback failure")
        return real_replace(source, destination)

    monkeypatch.setattr(
        update_tag_mappings.os,
        "replace",
        fail_second_new_file_and_first_rollback,
    )

    with pytest.raises(RuntimeError, match="rollback was incomplete"):
        update_tag_mappings._write_generated_files_transactionally(  # pylint: disable=protected-access
            {first: "VALUE = 'new-first'\n", second: "VALUE = 'new-second'\n"}
        )

    backups = list(tmp_path.glob(".first.py.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "VALUE = 'old-first'\n"
