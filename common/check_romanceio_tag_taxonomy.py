#!/usr/bin/env python3
"""Check Romance.io's live tag taxonomy against the plugin's bundled data.

The check tries HTTP first, with optional installed-plugin browser recovery.
It validates both slug-to-display-name mappings
and the content-warning, geography, and format categories used by the JSON path.
"""

import argparse
import html
import importlib
from types import ModuleType
import os
from pathlib import Path
import re
import sys
from typing import Dict, List, Optional, Set, Tuple
from urllib.error import HTTPError
from urllib.request import Request

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
BOOK_SOURCE_URL = "https://www.romance.io/books/65b604fa00d361e53f20ecfb/funny-story-emily-henry"
TOPICS_SOURCE_URL = "https://www.romance.io/topics/best/all/1"
HEADER_TO_CATEGORY = {
    "content warnings": "content_warnings",
    "geography": "geography_tags",
    "Format": "format_tags",
}
# ``undefined`` is Romance.io's internal key for the page-count control. It is
# present in special_tags but is not a selectable or book-level tag.
NON_TAG_SPECIAL_SLUGS = {"undefined"}


def extract_special_tag_taxonomy(html_content: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Extract category and display-name mappings from ``special_tags``."""
    import json

    match = re.search(r"\bvar\s+special_tags\s*=\s*(\{.*?\})\s*;", html_content, re.DOTALL)
    if not match:
        raise ValueError("Romance.io book page did not contain the special_tags taxonomy")

    raw_tags = json.loads(match.group(1))
    if not isinstance(raw_tags, dict):
        raise ValueError("Romance.io special_tags value was not an object")

    categories: Dict[str, str] = {}
    display_names: Dict[str, str] = {}
    for slug, metadata in raw_tags.items():
        if not isinstance(slug, str) or not slug or not isinstance(metadata, dict):
            raise ValueError(f"Invalid special_tags entry: {slug!r}")
        if slug in NON_TAG_SPECIAL_SLUGS:
            continue
        title = metadata.get("title")
        header = metadata.get("header")
        if not isinstance(title, str) or not title:
            raise ValueError(f"Invalid Romance.io display name for slug {slug!r}: {title!r}")
        if header not in HEADER_TO_CATEGORY:
            raise ValueError(f"Unknown Romance.io tag category {header!r} for slug {slug!r}")
        categories[slug] = HEADER_TO_CATEGORY[header]
        display_names[slug] = title

    if len(categories) < 300:
        raise ValueError(f"Only found {len(categories)} special tags; refusing a likely incomplete taxonomy")
    return categories, display_names


def extract_special_tag_categories(html_content: str) -> Dict[str, str]:
    """Compatibility helper returning just the special-tag categories."""
    return extract_special_tag_taxonomy(html_content)[0]


def extract_topic_display_names(html_content: str) -> Dict[str, str]:
    """Extract slug-to-title mappings from rendered or JSON-escaped topic links."""
    normalized = html_content.replace(r"\"", '"')
    pattern = r'<a class="topic-link" data-href="([^"]+)"[^>]*data-title="([^"]+)"'
    mappings = {html.unescape(slug): html.unescape(title) for slug, title in re.findall(pattern, normalized)}
    if len(mappings) < 300:
        raise ValueError(f"Only found {len(mappings)} topic tags; refusing a likely incomplete taxonomy")
    return mappings


def _access_modules(browser_fallback):
    """Use one module namespace so HTTP, cooldowns and browser cookies agree."""
    if str(WORKSPACE_DIR) not in sys.path:
        sys.path.insert(0, str(WORKSPACE_DIR))
    prefix = "calibre_plugins.romanceio_fields." if browser_fallback else "common."
    try:
        return {
            name: importlib.import_module(prefix + "common_romanceio_" + name)
            for name in ("transport", "session", "search_orchestrator", "fetch_helper", "webengine")
        }
    except ImportError as error:
        raise RuntimeError(
            "Browser recovery requires calibre-debug and the installed Romance.io Fields plugin"
        ) from error


def fetch_live_html(
    url: str, attempts: int = 3, browser_fallback: bool = False, modules: Optional[Dict[str, ModuleType]] = None
) -> str:
    """Fetch taxonomy HTML with production pacing, cookies and optional browsers."""
    modules = modules or _access_modules(browser_fallback)
    transport = modules["transport"]
    orchestrator = modules["search_orchestrator"]
    helper = modules["fetch_helper"]
    session = modules["session"]
    marker = "special_tags" if "/books/" in url else "topic-link"

    @transport.lookup_budget
    def fetch(abort=None, log_func=print):
        def http():
            log_func(f"Taxonomy HTTP request: {url}")
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            clearance = session.clearance_headers(url)
            headers.update(clearance)
            try:
                with transport.open_request(Request(url, headers=headers), timeout=30) as response:
                    content = response.read(5 * 1024 * 1024 + 1)
                if len(content) > 5 * 1024 * 1024:
                    raise ValueError("Taxonomy page exceeds the 5 MiB response limit")
            except HTTPError as error:
                if error.code == 403:
                    if clearance:
                        session.discard_clearance(clearance.get("Cookie", ""))
                    raise helper.HttpAccessDeniedError(f"Taxonomy HTTP access denied (403): {url}") from error
                if error.code == 429:
                    raise transport.HttpRateLimitError(
                        f"Taxonomy request rate limited (429): {url}",
                        retry_after=error.headers.get("Retry-After") if error.headers is not None else None,
                    ) from error
                raise
            page = content.decode("utf-8", errors="replace")
            title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            if not modules["webengine"].page_ready(
                page, title.group(1) if title else "", {"url": url, "wait_for_element": marker}
            ):
                raise helper.HttpAccessDeniedError("HTTP returned a challenge or incomplete taxonomy page")
            # Keep the retry logger from printing the entire HTML document.
            return (page,)

        result = orchestrator._retry_with_delay(
            http, "Taxonomy HTTP", max_retries=attempts, retry_delay=2, log_func=log_func, abort=abort
        )
        if result.success and result.result:
            return result.result[0]
        if not browser_fallback:
            raise RuntimeError(f"Could not fetch {url}; browser recovery was not enabled")
        log_func("Taxonomy HTTP unavailable; trying Qt, then Chrome if needed")
        return helper.fetch_page(
            url,
            plugin_name="romanceio_fields",
            wait_for_element=marker,
            max_wait=30,
            log_func=log_func,
            abort=abort,
        )

    return fetch()


def fetch_live_pages(browser_fallback=False):
    modules = _access_modules(browser_fallback)

    @modules["transport"].job_session
    def fetch():
        return tuple(
            fetch_live_html(url, browser_fallback=browser_fallback, modules=modules)
            for url in (BOOK_SOURCE_URL, TOPICS_SOURCE_URL)
        )

    return fetch()


def load_bundled_taxonomy() -> Tuple[Dict[str, str], Dict[str, str], Set[str], int]:
    """Load the shared mappings exactly as the plugins consume them."""
    if str(WORKSPACE_DIR) not in sys.path:
        sys.path.insert(0, str(WORKSPACE_DIR))
    from common.common_romanceio_tag_mappings import (  # pylint: disable=import-outside-toplevel
        JSON_TO_UI_TAG_MAP,
        SPECIAL_TAG_CATEGORIES,
        TAGS_TO_IGNORE,
        TOPIC_TAG_COUNT,
    )

    return dict(SPECIAL_TAG_CATEGORIES), dict(JSON_TO_UI_TAG_MAP), set(TAGS_TO_IGNORE), TOPIC_TAG_COUNT


def required_display_mappings(
    display_names: Dict[str, str],
    tags_to_ignore: Set[str],
    categorized_slugs: Set[str],
) -> Dict[str, str]:
    """Return live display names that cannot safely pass through as their slug."""
    return {
        slug: title
        for slug, title in display_names.items()
        if slug != title and (slug not in tags_to_ignore or slug in categorized_slugs)
    }


def _difference_lines(
    live_categories: Dict[str, str],
    live_display_names: Dict[str, str],
    bundled_categories: Dict[str, str],
    bundled_display_names: Dict[str, str],
    tags_to_ignore: Set[str],
    live_topic_count: Optional[int] = None,
    bundled_topic_count: Optional[int] = None,
    strict: bool = False,
) -> List[str]:
    lines: List[str] = []
    new_categories = sorted(set(live_categories) - set(bundled_categories))
    changed_categories = sorted(
        slug
        for slug in set(live_categories) & set(bundled_categories)
        if live_categories[slug] != bundled_categories[slug]
    )

    removed_categories = sorted(set(bundled_categories) - set(live_categories)) if strict else []

    required_names = required_display_mappings(live_display_names, tags_to_ignore, set(live_categories))
    new_names = sorted(set(required_names) - set(bundled_display_names))
    changed_names = sorted(
        slug
        for slug in set(required_names) & set(bundled_display_names)
        if required_names[slug] != bundled_display_names[slug]
    )
    removed_names = sorted(set(bundled_display_names) - set(required_names)) if strict else []

    if new_categories:
        lines.append("New categorized tags:")
        lines.extend(f"  {slug!r}: {live_categories[slug]!r}" for slug in new_categories)
    if changed_categories:
        lines.append("Tags moved to a different category:")
        lines.extend(
            f"  {slug!r}: {bundled_categories[slug]!r} -> {live_categories[slug]!r}" for slug in changed_categories
        )
    if removed_categories:
        lines.append("Categorized tags removed from the live taxonomy:")
        lines.extend(f"  {slug!r}: {bundled_categories[slug]!r}" for slug in removed_categories)
    if (
        strict
        and live_topic_count is not None
        and bundled_topic_count is not None
        and live_topic_count != bundled_topic_count
    ):
        lines.append("Topic-tag count changed: " f"bundled={bundled_topic_count}, live={live_topic_count}")
    if new_names:
        lines.append("New slug-to-display-name mappings:")
        lines.extend(f"  {slug!r}: {required_names[slug]!r}" for slug in new_names)
    if changed_names:
        lines.append("Changed display names:")
        lines.extend(
            f"  {slug!r}: {bundled_display_names[slug]!r} -> {required_names[slug]!r}" for slug in changed_names
        )
    if removed_names:
        lines.append("Obsolete slug-to-display-name mappings:")
        lines.extend(f"  {slug!r}: {bundled_display_names[slug]!r}" for slug in removed_names)
    return lines


def _write_github_summary(lines: List[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    if lines:
        body = [
            "## Romance.io tag taxonomy changed",
            "",
            "This is an expected maintenance signal, not a broken test pipeline.",
            "Romance.io added, removed, or renamed tags, or changed a tag category.",
            "",
            "```text",
            *lines,
            "```",
            "",
            "Run `python common/update_tag_mappings.py`, review the generated changes, and commit them.",
        ]
    else:
        body = [
            "## Romance.io tag taxonomy is current",
            "",
            "The bundled display-name and category mappings match the live site.",
        ]
    Path(summary_path).write_text("\n".join(body) + "\n", encoding="utf-8")


def compare_taxonomy(
    live_categories: Dict[str, str],
    live_display_names: Dict[str, str],
    live_topic_count: Optional[int] = None,
    strict: bool = True,
) -> bool:
    """Report actionable taxonomy differences and return whether data is current."""
    bundled_categories, bundled_display_names, tags_to_ignore, bundled_topic_count = load_bundled_taxonomy()
    lines = _difference_lines(
        live_categories,
        live_display_names,
        bundled_categories,
        bundled_display_names,
        tags_to_ignore,
        live_topic_count=live_topic_count,
        bundled_topic_count=bundled_topic_count,
        strict=strict,
    )
    _write_github_summary(lines)
    if lines:
        print("Romance.io's tag taxonomy changed; the plugin mappings need a routine refresh.")
        for line in lines:
            print(line)
        print("Run: python common/update_tag_mappings.py")
        if os.environ.get("GITHUB_ACTIONS"):
            print(
                "::error title=Romance.io tag taxonomy changed::"
                "This is a maintenance alert, not a broken pipeline. "
                "Run python common/update_tag_mappings.py."
            )
        return False

    print(
        "Bundled mappings handle all "
        f"{len(live_categories)} categorized tags and {len(live_display_names)} discovered display names."
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Check the live Romance.io taxonomy")
    parser.add_argument(
        "--browser-fallback",
        action="store_true",
        help="Use the installed Fields plugin for Qt/Chrome recovery (run with calibre-debug)",
    )
    parser.add_argument("--book-html-file", type=Path, help="Use a saved Romance.io book page")
    parser.add_argument("--topics-html-file", type=Path, help="Use a saved Romance.io topics page")
    args = parser.parse_args()

    if args.browser_fallback and not args.live:
        parser.error("--browser-fallback requires --live")
    if args.live and (args.book_html_file or args.topics_html_file):
        parser.error("--live cannot be combined with saved HTML files")
    if bool(args.book_html_file) != bool(args.topics_html_file):
        parser.error("provide both --book-html-file and --topics-html-file")
    if not args.live and not args.book_html_file:
        parser.error("pass --live or provide both saved HTML files")

    try:
        if args.book_html_file:
            book_html = args.book_html_file.read_text(encoding="utf-8")
            topics_html = args.topics_html_file.read_text(encoding="utf-8")
        else:
            book_html, topics_html = fetch_live_pages(browser_fallback=args.browser_fallback)

        categories, special_display_names = extract_special_tag_taxonomy(book_html)
        topic_display_names = extract_topic_display_names(topics_html)
        all_display_names = {**special_display_names, **topic_display_names}
        return (
            0
            if compare_taxonomy(
                categories,
                all_display_names,
                live_topic_count=len(topic_display_names),
                strict=not bool(args.book_html_file),
            )
            else 1
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Romance.io taxonomy check could not run: {error}", file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=Romance.io taxonomy check could not run::{error}")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as output:
                output.write(f"## Romance.io taxonomy check unavailable\n\nNo comparison was completed: {error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
