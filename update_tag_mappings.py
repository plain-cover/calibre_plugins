#!/usr/bin/env python3
"""
Update JSON_TO_UI_TAG_MAP in common/common_romanceio_tag_mappings.py by fetching latest tags from Romance.io.

This script runs automatically during build if tag mappings are >30 days old.
Can also be run manually from the workspace root: python update_tag_mappings.py
"""

from datetime import datetime
import html
import re
import sys
import types
from pathlib import Path


def setup_imports():
    """Set up module imports for standalone execution and build integration."""
    workspace_dir = Path(__file__).parent

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
    """Validate that a tag value is safe to write to Python source code.

    Ensures value:
    - Contains only safe characters (alphanumeric, spaces, hyphens, ampersands, apostrophes, etc.)
    - Has reasonable length (1-100 chars)
    - Doesn't contain quotes, backslashes, or control characters that could break Python syntax
    """
    if not value or not isinstance(value, str):
        return False

    if len(value) > 100:
        return False

    # Allow: letters, numbers, spaces, hyphens, ampersands, apostrophes, parentheses, slashes, colons, plus signs
    # Reject: quotes, backslashes, control chars, other special chars that could inject code
    safe_pattern = r"^[a-zA-Z0-9 &\'\-/():+]+$"
    return bool(re.match(safe_pattern, value))


def extract_tag_mappings_from_html(html_content):
    """Extract data-href and data-title pairs from HTML content."""
    pattern = r'<a class="topic-link" data-href="([^"]+)" data-title="([^"]+)"'
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
        print(f"[update_tag_mappings] ⚠ Skipped {len(skipped)} potentially unsafe tag mappings:")
        for href, title in skipped[:5]:
            print(f'[update_tag_mappings]   "{href}" -> "{title}"')
        if len(skipped) > 5:
            print(f"[update_tag_mappings]   ... and {len(skipped) - 5} more")

    return validated_mappings


def parse_existing_mappings(parse_json_file):
    """Parse existing JSON_TO_UI_TAG_MAP from common_romanceio_tag_mappings.py."""
    with open(parse_json_file, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.search(r"JSON_TO_UI_TAG_MAP = \{([^}]+)\}", content, re.DOTALL)
    if not match:
        raise ValueError("Could not find JSON_TO_UI_TAG_MAP in common_romanceio_tag_mappings.py")

    dict_content = match.group(1)

    existing = {}
    for line in dict_content.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Match: "key": "value",
        kv_match = re.match(r'"([^"]+)":\s*"([^"]+)",?', line)
        if kv_match:
            # Decode HTML entities (e.g., &amp; -> &) when reading existing mappings
            key_decoded = html.unescape(kv_match.group(1))
            value_decoded = html.unescape(kv_match.group(2))
            existing[key_decoded] = value_decoded

    return existing


def find_new_mappings(html_mappings, existing_mappings, tags_to_ignore):
    """Find mappings in HTML that aren't in existing dict or have different values."""
    new_mappings = {}

    for href, title in html_mappings.items():
        if href == title:
            continue
        if href in tags_to_ignore:
            continue
        if href not in existing_mappings:
            new_mappings[href] = title
        elif existing_mappings[href] != title:
            new_mappings[href] = title

    return new_mappings


def update_parse_json(parse_json_file, new_mappings, existing_mappings):
    """Add new mappings to JSON_TO_UI_TAG_MAP in common_romanceio_tag_mappings.py, keeping everything alphabetized."""
    with open(parse_json_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the JSON_TO_UI_TAG_MAP dict location (including any preceding comment)
    match = re.search(
        r"(# Last tag mapping update: \d{4}-\d{2}-\d{2}\n)?(JSON_TO_UI_TAG_MAP = \{[^}]+\})", content, re.DOTALL
    )
    if not match:
        raise ValueError("Could not find JSON_TO_UI_TAG_MAP in common_romanceio_tag_mappings.py")

    all_mappings = {**existing_mappings, **new_mappings}

    invalid = [(k, v) for k, v in all_mappings.items() if not (is_safe_tag_value(k) and is_safe_tag_value(v))]
    if invalid:
        print("[update_tag_mappings] ✗ Invalid tag mappings detected:")
        for k, v in invalid:
            print(f'[update_tag_mappings]   "{k}" -> "{v}"')
            print(f"[update_tag_mappings]     Key valid: {is_safe_tag_value(k)}, Value valid: {is_safe_tag_value(v)}")
        raise ValueError(f"Refusing to write {len(invalid)} invalid tag mappings to source file")

    # Build the new dict with all mappings alphabetically sorted
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"# Last tag mapping update: {today}"]
    lines.append("JSON_TO_UI_TAG_MAP = {")
    for key in sorted(all_mappings.keys()):
        value = all_mappings[key]
        lines.append(f'    "{key}": "{value}",')
    lines.append("}")

    new_dict = "\n".join(lines)

    new_content = content[: match.start()] + new_dict + content[match.end() :]

    with open(parse_json_file, "w", encoding="utf-8") as f:
        f.write(new_content)


def update_tag_mappings():
    """Main function to update tag mappings from Romance.io."""
    setup_imports()

    from common.common_romanceio_fetch_helper import fetch_page
    from common.common_romanceio_tag_mappings import TAGS_TO_IGNORE

    workspace_dir = Path(__file__).parent
    tag_mappings_file = workspace_dir / "common" / "common_romanceio_tag_mappings.py"

    url = "https://www.romance.io/topics/best/all/1"

    print(f"[update_tag_mappings] Fetching page from: {url}")
    print("[update_tag_mappings] This may take a moment as Chrome launches...")

    html_content = fetch_page(url, plugin_name="romanceio_fields", wait_for_element="topic-link", max_wait=30)

    if not html_content:
        print("[update_tag_mappings] ✗ Failed to fetch page")
        return False

    print("[update_tag_mappings] Extracting tag mappings from HTML...")
    html_mappings = extract_tag_mappings_from_html(html_content)
    print(f"[update_tag_mappings] Found {len(html_mappings)} tag mappings in HTML")

    print(f"[update_tag_mappings] Reading existing mappings from: {tag_mappings_file}")
    existing_mappings = parse_existing_mappings(tag_mappings_file)
    print(f"[update_tag_mappings] Found {len(existing_mappings)} existing mappings")

    new_mappings = find_new_mappings(html_mappings, existing_mappings, TAGS_TO_IGNORE)

    if not new_mappings:
        print("[update_tag_mappings] ✓ No new mappings to add. All tags are already current.")
        # Still update the date comment to reset the timer
        print("[update_tag_mappings] Updating last update date...")
        update_parse_json(tag_mappings_file, {}, existing_mappings)
        return True

    print(f"[update_tag_mappings] Found {len(new_mappings)} new mappings to add:")
    for key in sorted(new_mappings.keys()):
        value = new_mappings[key]
        if key in existing_mappings:
            print(f'[update_tag_mappings]   "{key}": "{value}"  (UPDATE from "{existing_mappings[key]}")')
        else:
            print(f'[update_tag_mappings]   "{key}": "{value}"  (NEW)')

    print(f"[update_tag_mappings] Updating {tag_mappings_file}...")
    update_parse_json(tag_mappings_file, new_mappings, existing_mappings)
    print("[update_tag_mappings] ✓ Successfully updated common_romanceio_tag_mappings.py")
    return True


if __name__ == "__main__":
    SUCCESS = update_tag_mappings()
    sys.exit(0 if SUCCESS else 1)
