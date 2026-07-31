#!/usr/bin/env python3
"""
Update Romance.io tag display-name and category mappings by fetching the latest taxonomy.

Run it explicitly from the workspace root: python common/update_tag_mappings.py
Builds only validate committed mappings and never fetch or rewrite taxonomy data.
"""

from datetime import datetime
import ast
import html
import os
import re
import sys
import tempfile
import types
from pathlib import Path
from typing import Dict


def setup_imports():
    """Set up module imports for standalone execution and build integration."""
    workspace_dir = Path(__file__).resolve().parent.parent

    if str(workspace_dir) not in sys.path:
        sys.path.insert(0, str(workspace_dir))

    # Set up calibre_plugins module structure
    calibre_plugins = types.ModuleType("calibre_plugins")
    calibre_plugins.__path__ = [str(workspace_dir)]
    sys.modules["calibre_plugins"] = calibre_plugins

    # Set up romanceio_fields as a submodule (needed by fetch_helper for vendored deps)
    romanceio_fields_module = types.ModuleType("calibre_plugins.romanceio_fields")
    romanceio_fields_module.__path__ = [str(workspace_dir / "romanceio_fields")]
    sys.modules["calibre_plugins.romanceio_fields"] = romanceio_fields_module


def is_safe_tag_value(value: str) -> bool:
    """Validate a tag value before writing it as an escaped Python literal.

    Ensures value:
    - Has reasonable length (1-100 chars)
    - Contains no control or other non-printable characters

    Punctuation and Unicode are safe because generated keys and values are
    emitted with ``repr`` rather than interpolated inside hand-built quotes.
    """
    if not isinstance(value, str) or not value:
        return False

    if len(value) > 100:
        return False

    return value.isprintable()


def extract_tag_mappings_from_html(html_content):
    """Extract topic slugs and titles from rendered or JSON-escaped HTML."""
    html_content = html_content.replace(r'\"', '"')
    pattern = r'<a class="topic-link" data-href="([^"]+)"[^>]*data-title="([^"]+)"'
    matches = re.findall(pattern, html_content)

    # Decode HTML entities (like &amp; -> &) and return as dict
    # Only include mappings where both key and value pass validation
    validated_mappings = {}
    skipped = []

    for href, title in matches:
        href_decoded = html.unescape(href)
        title_decoded = html.unescape(title)

        if is_safe_tag_value(href_decoded) and is_safe_tag_value(title_decoded):
            validated_mappings[href_decoded] = title_decoded
        else:
            skipped.append((href_decoded, title_decoded))

    if skipped:
        print(f"[update_tag_mappings] WARNING: Skipped {len(skipped)} potentially unsafe tag mappings:")
        for href, title in skipped[:5]:
            print(f'[update_tag_mappings]   "{href}" -> "{title}"')
        if len(skipped) > 5:
            print(f"[update_tag_mappings]   ... and {len(skipped) - 5} more")

    return validated_mappings


def parse_existing_mappings(parse_json_file):
    """Parse existing JSON_TO_UI_TAG_MAP from common_romanceio_tag_mappings.py."""
    with open(parse_json_file, "r", encoding="utf-8") as f:
        content = f.read()

    assignment = _find_mapping_assignment(content)
    try:
        existing = ast.literal_eval(assignment.value)
    except (TypeError, ValueError) as error:
        raise ValueError("JSON_TO_UI_TAG_MAP was not a literal dictionary") from error
    if not isinstance(existing, dict):
        raise ValueError("JSON_TO_UI_TAG_MAP was not a dictionary")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in existing.items()):
        raise ValueError("JSON_TO_UI_TAG_MAP contained a non-string key or value")
    return existing


def _find_mapping_assignment(content: str) -> ast.Assign:
    """Return the AST assignment for ``JSON_TO_UI_TAG_MAP``."""
    try:
        tree = ast.parse(content)
    except SyntaxError as error:
        raise ValueError("common_romanceio_tag_mappings.py was not valid Python") from error

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "JSON_TO_UI_TAG_MAP" for target in node.targets):
            return node

    raise ValueError("Could not find JSON_TO_UI_TAG_MAP in common_romanceio_tag_mappings.py")


def _mapping_section_bounds(content: str, assignment: ast.Assign) -> tuple[int, int]:
    """Locate the generated header and mapping assignment in source text."""
    source_lines = content.splitlines(keepends=True)
    assignment_start = sum(len(line) for line in source_lines[: assignment.lineno - 1])
    section_start = content.rfind("# Last tag mapping update: ", 0, assignment_start)
    if section_start < 0:
        raise ValueError("Could not find JSON_TO_UI_TAG_MAP in common_romanceio_tag_mappings.py")

    assignment_end_lineno = assignment.end_lineno
    if assignment_end_lineno is None:
        raise ValueError("JSON_TO_UI_TAG_MAP assignment did not have source positions")
    assignment_end_line = source_lines[assignment_end_lineno - 1]
    assignment_end = sum(len(line) for line in source_lines[: assignment_end_lineno - 1])
    assignment_end += len(assignment_end_line.rstrip("\r\n"))
    return section_start, assignment_end


def render_tag_mapping_module(parse_json_file, mappings, topic_tag_count):
    """Return the mapping module with its generated section replaced exactly."""
    with open(parse_json_file, "r", encoding="utf-8") as f:
        content = f.read()

    assignment = _find_mapping_assignment(content)
    section_start, section_end = _mapping_section_bounds(content, assignment)

    invalid = [
        (key, value)
        for key, value in mappings.items()
        if not (is_safe_tag_value(key) and is_safe_tag_value(value))
    ]
    if invalid:
        print("[update_tag_mappings] ERROR: Invalid tag mappings detected:")
        for k, v in invalid:
            print(f'[update_tag_mappings]   "{k}" -> "{v}"')
            print(f"[update_tag_mappings]     Key valid: {is_safe_tag_value(k)}, Value valid: {is_safe_tag_value(v)}")
        raise ValueError(f"Refusing to write {len(invalid)} invalid tag mappings to source file")

    # Build the new dict with all mappings alphabetically sorted
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# Last tag mapping update: {today}",
        "# Number of topic tags seen during the same update. This includes identity",
        "# mappings, which are intentionally omitted from JSON_TO_UI_TAG_MAP.",
        f"TOPIC_TAG_COUNT = {topic_tag_count}",
    ]
    lines.append("JSON_TO_UI_TAG_MAP = {")
    for key in sorted(mappings):
        value = mappings[key]
        lines.append(f"    {key!r}: {value!r},")
    lines.append("}")

    new_dict = "\n".join(lines)

    return content[:section_start] + new_dict + content[section_end:]


def render_category_module(categories):
    """Return the complete generated shared category module."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        '"""Bundled Romance.io tag-category map.',
        "",
        "Generated by ``update_tag_mappings.py`` from Romance.io's ``special_tags``",
        "taxonomy. Do not edit this file by hand.",
        '"""',
        "",
        "from typing import Dict",
        "",
        f"# Last category mapping update: {today}",
        "SPECIAL_TAG_CATEGORIES: Dict[str, str] = {",
    ]
    for slug in sorted(categories):
        lines.append(f"    {slug!r}: {categories[slug]!r},")
    lines.extend(["}", ""])
    return "\n".join(lines)


def _stage_text_file(destination: Path, content: str, marker: str) -> Path:
    """Write and flush a temporary sibling file for a later atomic replacement."""
    descriptor, filename = tempfile.mkstemp(
        prefix=f".{destination.name}.{marker}-",
        dir=str(destination.parent),
    )
    staged_path = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as staged_file:
            staged_file.write(content)
            staged_file.flush()
            os.fsync(staged_file.fileno())
    except Exception:
        if staged_path.exists():
            staged_path.unlink()
        raise
    return staged_path


def _write_generated_files_transactionally(generated_files: Dict[Path, str]) -> None:
    """Validate and replace generated Python files, rolling back on write failure."""
    original_contents = {path: path.read_text(encoding="utf-8") for path in generated_files}
    for path, content in generated_files.items():
        compile(content, str(path), "exec")

    staged_new: Dict[Path, Path] = {}
    staged_backups: Dict[Path, Path] = {}
    preserved_backups = set()
    replaced = []
    try:
        for path, content in generated_files.items():
            staged_new[path] = _stage_text_file(path, content, "new")
            staged_backups[path] = _stage_text_file(path, original_contents[path], "backup")

        for path in generated_files:
            os.replace(staged_new[path], path)
            replaced.append(path)
    except Exception as error:
        rollback_errors = []
        for path in reversed(replaced):
            try:
                os.replace(staged_backups[path], path)
            except OSError as rollback_error:
                backup_path = staged_backups[path]
                preserved_backups.add(backup_path)
                rollback_errors.append(
                    f"{path}: {rollback_error}; original preserved at {backup_path}"
                )
        if rollback_errors:
            raise RuntimeError(
                "Generated taxonomy update failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from error
        raise
    finally:
        for staged_path in [*staged_new.values(), *staged_backups.values()]:
            if staged_path not in preserved_backups and staged_path.exists():
                staged_path.unlink()


def update_tag_mappings():
    """Main function to update tag mappings from Romance.io."""
    setup_imports()

    from common.check_romanceio_tag_taxonomy import (
        BOOK_SOURCE_URL,
        TOPICS_SOURCE_URL,
        extract_special_tag_taxonomy,
        extract_topic_display_names,
        fetch_live_html,
        required_display_mappings,
    )
    from common.common_romanceio_fetch_helper import fetch_page
    from common.common_romanceio_tag_mappings import TAGS_TO_IGNORE

    workspace_dir = Path(__file__).resolve().parent.parent
    tag_mappings_file = workspace_dir / "common" / "common_romanceio_tag_mappings.py"
    category_file = workspace_dir / "common" / "common_romanceio_tag_categories.py"

    print(f"[update_tag_mappings] Fetching tag categories from: {BOOK_SOURCE_URL}")
    try:
        category_html = fetch_live_html(BOOK_SOURCE_URL)
        category_mappings, special_display_names = extract_special_tag_taxonomy(category_html)
    except (RuntimeError, ValueError) as error:
        print(f"[update_tag_mappings] Plain HTTP category fetch failed: {error}")
        print("[update_tag_mappings] Falling back to Chrome for the maintainer-side mapping update...")
        category_html = fetch_page(
            BOOK_SOURCE_URL,
            plugin_name="romanceio_fields",
            wait_for_element="book-stats",
            max_wait=30,
        )
        if not category_html:
            print("[update_tag_mappings] Failed to fetch the Romance.io category taxonomy")
            return False
        category_mappings, special_display_names = extract_special_tag_taxonomy(category_html)
    if not category_html:
        print("[update_tag_mappings] Failed to fetch the Romance.io category taxonomy")
        return False

    print(f"[update_tag_mappings] Fetching display names from: {TOPICS_SOURCE_URL}")
    try:
        html_content = fetch_live_html(TOPICS_SOURCE_URL)
        topic_display_names = extract_topic_display_names(html_content)
    except (RuntimeError, ValueError) as error:
        print(f"[update_tag_mappings] Plain HTTP topics fetch failed: {error}")
        print("[update_tag_mappings] Falling back to Chrome for the maintainer-side mapping update...")
        html_content = fetch_page(
            TOPICS_SOURCE_URL,
            plugin_name="romanceio_fields",
            wait_for_element="topic-link",
            max_wait=30,
        )
        topic_display_names = extract_tag_mappings_from_html(html_content) if html_content else {}

    if not html_content or len(topic_display_names) < 300:
        print(
            "[update_tag_mappings] ERROR: Failed to fetch a complete topics taxonomy "
            f"(found {len(topic_display_names)} tags)"
        )
        return False

    html_mappings = {**special_display_names, **topic_display_names}
    print(f"[update_tag_mappings] Found {len(html_mappings)} tag mappings in HTML")

    print(f"[update_tag_mappings] Reading existing mappings from: {tag_mappings_file}")
    existing_mappings = parse_existing_mappings(tag_mappings_file)
    print(f"[update_tag_mappings] Found {len(existing_mappings)} existing mappings")

    desired_mappings = required_display_mappings(
        html_mappings,
        TAGS_TO_IGNORE,
        set(category_mappings),
    )
    added = sorted(set(desired_mappings) - set(existing_mappings))
    changed = sorted(
        slug
        for slug in set(desired_mappings) & set(existing_mappings)
        if desired_mappings[slug] != existing_mappings[slug]
    )
    removed = sorted(set(existing_mappings) - set(desired_mappings))

    for slug in added:
        print(f'[update_tag_mappings]   "{slug}": "{desired_mappings[slug]}"  (NEW)')
    for slug in changed:
        print(
            f'[update_tag_mappings]   "{slug}": "{desired_mappings[slug]}"  '
            f'(UPDATE from "{existing_mappings[slug]}")'
        )
    for slug in removed:
        print(f'[update_tag_mappings]   "{slug}": "{existing_mappings[slug]}"  (REMOVE)')
    if not (added or changed or removed):
        print("[update_tag_mappings] Display-name mappings are already current.")

    # Render and validate both modules before replacing either one. The writer
    # stages backups and restores already-replaced files if a later replace fails.
    generated_files = {
        category_file: render_category_module(category_mappings),
        tag_mappings_file: render_tag_mapping_module(
            tag_mappings_file,
            desired_mappings,
            len(topic_display_names),
        ),
    }
    _write_generated_files_transactionally(generated_files)
    print(f"[update_tag_mappings] Updated {len(category_mappings)} bundled special-tag categories")
    print(f"[update_tag_mappings] Updated {len(desired_mappings)} display-name mappings")
    return True


if __name__ == "__main__":
    SUCCESS = update_tag_mappings()
    sys.exit(0 if SUCCESS else 1)
