"""Test Romance.io SSR HTML field parsing (lightweight HTTP fetch path).

The lightweight HTTP fetch path (fetch_book_page_http) retrieves the server-side
rendered HTML without Chrome. This file verifies:

1. parse_tags_from_description() - extracts tags from the <meta name="description">
   attribute; these match the JSON API 'tropes' field exactly.
2. parse_fields_from_ssr_html() - combines book-stats-based rating parsers (same as
   Chrome) with description-based combined tags and embedded categorized tags.
3. SSR vs JSON API parity - tags from SSR == tags from JSON API (same underlying source).
4. SSR vs Chrome comparison - ratings are identical; SSR tags are a subset of Chrome tags.

Static HTML test data files were captured via Chrome and contain BOTH:
  - The <meta name="description"> SSR content (server-side, same as plain HTTP response)
  - The server-provided tagged_topics category data and rendered tagged-topic elements
This makes them the correct ground truth for SSR tests: the description text is SSR,
the embedded object preserves categories, and the rendered count gives the Chrome upper bound.

To run:
    calibre-debug -e test_http_fields_parsing.py
"""

import os
import re
import sys
import types
from typing import Callable, List

from lxml.html import HtmlElement, fromstring

# Set up module path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common.test_data import load_plugin_module
from common.common_romanceio_static_test_data import (
    STATIC_TEST_BOOKS,
    StaticTestBook,
    load_static_html_file,
    load_static_json_file,
)

# Make romanceio_fields a package
romanceio_fields = types.ModuleType("romanceio_fields")
romanceio_fields.__path__ = [plugin_dir]
sys.modules["romanceio_fields"] = romanceio_fields

# Load modules under test (no Qt/calibre dependencies needed for parse functions)
tag_mappings = load_plugin_module(
    "romanceio_fields.common_romanceio_tag_mappings", "common_romanceio_tag_mappings.py", plugin_dir
)
parse_html_module = load_plugin_module("romanceio_fields.parse_html", "parse_html.py", plugin_dir)
parse_json_module = load_plugin_module("romanceio_fields.parse_json", "parse_json.py", plugin_dir)

parse_tags_from_description = parse_html_module.parse_tags_from_description
parse_tag_categories_from_html = parse_html_module.parse_tag_categories_from_html
has_tag_category_data = parse_html_module.has_tag_category_data
parse_fields_from_ssr_html = parse_html_module.parse_fields_from_ssr_html
parse_tags_from_js_html = parse_html_module.parse_tags_from_js_html
parse_steam_rating = parse_html_module.parse_steam_rating
parse_star_rating = parse_html_module.parse_star_rating
parse_rating_count = parse_html_module.parse_rating_count
parse_fields_from_html = parse_html_module.parse_fields_from_html
parse_fields_from_json = parse_json_module.parse_fields_from_json
convert_json_tags_to_display_names = tag_mappings.convert_json_tags_to_display_names


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_passed: List[str] = []
_failed: List[str] = []


def _run(test_name: str, func: Callable) -> None:
    print(f"\n  {test_name}...", end=" ")
    try:
        func()
        print("✓")
        _passed.append(test_name)
    except AssertionError as e:
        print(f"FAIL: {e}")
        _failed.append(test_name)
    except Exception as e:  # pylint: disable=broad-except
        print(f"ERROR: {type(e).__name__}: {e}")
        _failed.append(test_name)


def _load_html(filename: str) -> HtmlElement:
    raw_html = load_static_html_file(filename)
    # Use fromstring directly (same underlying call as parse_html_from_selenium)
    return fromstring(raw_html)


def _load_json_book(filename: str) -> dict:
    """Load the book dict from a static JSON file (book detail format)."""
    data = load_static_json_file(filename)
    # Static JSON detail files are the raw book object (not a search response)
    return data


# ---------------------------------------------------------------------------
# parse_tags_from_description tests
# ---------------------------------------------------------------------------


def _test_description_tags_non_empty(book: StaticTestBook) -> None:
    root = _load_html(book.html_filename)
    tags = parse_tags_from_description(root)
    assert len(tags) > 0, "Expected tags from description, got empty list"
    print(f"({len(tags)} tags)", end=" ")


def _test_description_tags_are_display_names(book: StaticTestBook) -> None:
    """Tags from description should be display names, not slugs."""
    root = _load_html(book.html_filename)
    tags = parse_tags_from_description(root)
    # A slug would contain a hyphen (e.g. "from-hate-to-love"); display names use spaces
    # Check that common slugs are correctly mapped
    raw_html = load_static_html_file(book.html_filename).decode("utf-8", errors="replace")
    desc_match = re.search(r'<meta name="description" content="([^"]+)"', raw_html)
    assert desc_match, "Expected meta description in HTML"
    tag_raw_match = re.search(r"is tagged as ([^.]+)\.", desc_match.group(1))
    assert tag_raw_match, "Expected 'is tagged as' in description"
    # If the slug set contains any mapped slugs, verify they appear as their display names
    slugs = [s.strip() for s in tag_raw_match.group(1).split(", ") if s.strip()]
    from common.common_romanceio_tag_mappings import JSON_TO_UI_TAG_MAP  # type: ignore[import-not-found]

    for slug in slugs:
        if slug in JSON_TO_UI_TAG_MAP:
            display = JSON_TO_UI_TAG_MAP[slug]
            assert display in tags, f"Slug '{slug}' should map to '{display}' but not found in {tags}"
            break  # One check is sufficient


def _test_description_tags_match_json_api(book: StaticTestBook) -> None:
    """SSR description tags must exactly match JSON API tags (same underlying source)."""
    root = _load_html(book.html_filename)
    ssr_tags = set(parse_tags_from_description(root))

    book_json = _load_json_book(book.json_filename)
    json_tags = set(parse_fields_from_json(book_json)["tags"])

    missing_from_ssr = json_tags - ssr_tags
    extra_in_ssr = ssr_tags - json_tags
    assert not missing_from_ssr and not extra_in_ssr, (
        f"SSR and JSON API tag sets differ.\n"
        f"  Missing from SSR ({len(missing_from_ssr)}): {sorted(missing_from_ssr)}\n"
        f"  Extra in SSR ({len(extra_in_ssr)}): {sorted(extra_in_ssr)}"
    )
    print(f"({len(ssr_tags)} tags, exact match)", end=" ")


def _test_description_tags_subset_of_chrome_tags(book: StaticTestBook) -> None:
    """Every SSR tag should also appear in Chrome's full tag set."""
    root = _load_html(book.html_filename)
    ssr_tags = set(parse_tags_from_description(root))
    chrome_tags = set(parse_tags_from_js_html(root))

    not_in_chrome = ssr_tags - chrome_tags
    assert not not_in_chrome, f"SSR tags not found in Chrome tag set: {sorted(not_in_chrome)}"
    print(f"(SSR {len(ssr_tags)} ⊆ Chrome {len(chrome_tags)})", end=" ")


def _test_description_tags_minimum_count(book: StaticTestBook) -> None:
    """SSR should return at least as many tags as the JSON API (≥ json_tag_count)."""
    root = _load_html(book.html_filename)
    ssr_tags = parse_tags_from_description(root)

    book_json = _load_json_book(book.json_filename)
    json_tags = parse_fields_from_json(book_json)["tags"]

    # SSR comes from the same source as JSON, so count must be equal
    assert len(ssr_tags) == len(json_tags), f"SSR tag count {len(ssr_tags)} != JSON tag count {len(json_tags)}"


def _test_description_tags_sample_present(book: StaticTestBook) -> None:
    """All sample_tags from StaticTestBook metadata should appear in SSR tags."""
    if not book.sample_tags:
        return
    root = _load_html(book.html_filename)
    ssr_tags = set(parse_tags_from_description(root))
    # Sample tags come from the Chrome tag set; some may be JS-only tags not in SSR.
    # Check only those that should be in both (i.e., also in JSON API).
    book_json = _load_json_book(book.json_filename)
    json_tags = set(parse_fields_from_json(book_json)["tags"])
    ssr_expected = [t for t in book.sample_tags if t in json_tags]
    missing = [t for t in ssr_expected if t not in ssr_tags]
    assert not missing, f"Expected sample tags not in SSR output: {missing}"
    print(f"(checked {len(ssr_expected)} sample tags)", end=" ")


def _test_description_tags_no_steam_leaked(book: StaticTestBook) -> None:
    """Steam level text should not appear in the tag list."""
    root = _load_html(book.html_filename)
    tags = parse_tags_from_description(root)
    steam_leak = [t for t in tags if "steam" in t.lower() or "spice" in t.lower() or "heat" in t.lower()]
    assert not steam_leak, f"Steam-level text leaked into tags: {steam_leak}"


# ---------------------------------------------------------------------------
# parse_fields_from_ssr_html tests
# ---------------------------------------------------------------------------


def _test_ssr_returns_dict(book: StaticTestBook) -> None:
    root = _load_html(book.html_filename)
    result = parse_fields_from_ssr_html(root)
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    required_keys = {
        "steam_rating",
        "star_rating",
        "rating_count",
        "tags",
        "general_tags",
        "content_warnings",
        "geography_tags",
        "format_tags",
    }
    assert required_keys.issubset(result.keys()), f"Missing keys: {required_keys - result.keys()}"


def _test_ssr_steam_rating_matches_chrome(book: StaticTestBook) -> None:
    """SSR steam rating should be identical to Chrome steam rating."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    chrome = parse_fields_from_html(root, max_tags=1000)
    assert (
        ssr["steam_rating"] == chrome["steam_rating"]
    ), f"Steam mismatch: SSR={ssr['steam_rating']}, Chrome={chrome['steam_rating']}"
    if book.steam_rating is not None:
        assert (
            ssr["steam_rating"] == book.steam_rating
        ), f"SSR steam {ssr['steam_rating']} != expected {book.steam_rating}"
    print(f"(steam={ssr['steam_rating']})", end=" ")


def _test_ssr_star_rating_matches_chrome(book: StaticTestBook) -> None:
    """SSR star rating should be identical to Chrome star rating (within float tolerance)."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    chrome = parse_fields_from_html(root, max_tags=1000)
    ssr_star = ssr["star_rating"]
    chrome_star = chrome["star_rating"]
    if ssr_star is not None and chrome_star is not None:
        assert (
            abs(ssr_star - chrome_star) < 0.01
        ), f"Star rating mismatch beyond tolerance: SSR={ssr_star}, Chrome={chrome_star}"
    else:
        assert ssr_star == chrome_star, f"Star mismatch: SSR={ssr_star}, Chrome={chrome_star}"
    if book.star_rating is not None and ssr_star is not None:
        assert (
            abs(ssr_star - book.star_rating) < 0.1
        ), f"SSR star {ssr_star} differs from expected {book.star_rating} by more than 0.1"
    print(f"(star={ssr_star})", end=" ")


def _test_ssr_rating_count_matches_chrome(book: StaticTestBook) -> None:
    """SSR rating count should be identical to Chrome rating count."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    chrome = parse_fields_from_html(root, max_tags=1000)
    assert (
        ssr["rating_count"] == chrome["rating_count"]
    ), f"Rating count mismatch: SSR={ssr['rating_count']}, Chrome={chrome['rating_count']}"
    if book.rating_count is not None and ssr["rating_count"] is not None:
        # Allow ±5% for live count drift (static file may be slightly old)
        tolerance = max(10, int(book.rating_count * 0.05))
        assert (
            abs(ssr["rating_count"] - book.rating_count) <= tolerance
        ), f"SSR count {ssr['rating_count']} differs from expected {book.rating_count} by more than {tolerance}"
    print(f"(count={ssr['rating_count']})", end=" ")


def _test_ssr_tags_match_json_api(book: StaticTestBook) -> None:
    """SSR tags (from description) must exactly match JSON API tags."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    book_json = _load_json_book(book.json_filename)
    json_fields = parse_fields_from_json(book_json)

    ssr_set = set(ssr["tags"])
    json_set = set(json_fields["tags"])
    missing = json_set - ssr_set
    extra = ssr_set - json_set
    assert not missing and not extra, (
        f"SSR tags differ from JSON API tags.\n"
        f"  Missing from SSR ({len(missing)}): {sorted(missing)}\n"
        f"  Extra in SSR ({len(extra)}): {sorted(extra)}"
    )
    print(f"({len(ssr_set)} tags, exact JSON match)", end=" ")


def _test_ssr_tags_subset_of_chrome(book: StaticTestBook) -> None:
    """Every SSR tag should also appear in Chrome's larger tag set."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    chrome = parse_fields_from_html(root, max_tags=1000)
    ssr_set = set(ssr["tags"])
    chrome_set = set(chrome["tags"])
    not_in_chrome = ssr_set - chrome_set
    assert not not_in_chrome, f"SSR tags not found in Chrome tag set: {sorted(not_in_chrome)}"
    print(f"(SSR {len(ssr_set)} ⊆ Chrome {len(chrome_set)})", end=" ")


def _test_ssr_max_tags_limiting(book: StaticTestBook) -> None:
    """max_tags parameter should correctly limit the number of tags returned."""
    root = _load_html(book.html_filename)
    all_tags = parse_fields_from_ssr_html(root)["tags"]
    if len(all_tags) < 5:
        return  # Not enough tags to test limiting

    result_10 = parse_fields_from_ssr_html(root, max_tags=10)
    result_5 = parse_fields_from_ssr_html(root, max_tags=5)
    result_1 = parse_fields_from_ssr_html(root, max_tags=1)

    assert len(result_10["tags"]) <= 10, f"Expected ≤10 tags, got {len(result_10['tags'])}"
    assert len(result_5["tags"]) == 5, f"Expected 5 tags, got {len(result_5['tags'])}"
    assert len(result_1["tags"]) == 1, f"Expected 1 tag, got {len(result_1['tags'])}"
    # Order should be stable and consistent with unlimited
    assert result_5["tags"] == all_tags[:5], "max_tags slicing should preserve order from front"
    for key in ("general_tags", "content_warnings", "geography_tags", "format_tags"):
        assert result_1[key] == result_10[key], f"max_tags must not truncate optional {key}"


def _test_ssr_no_steam_text_in_tags(book: StaticTestBook) -> None:
    """Steam level text should never appear in the tag list."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    steam_leak = [t for t in ssr["tags"] if "steam" in t.lower() or "spice" in t.lower()]
    assert not steam_leak, f"Steam text leaked into tags: {steam_leak}"


def _test_ssr_valid_steam_range(book: StaticTestBook) -> None:
    """Steam rating should be None or an integer in range 1-5."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    steam = ssr["steam_rating"]
    if steam is not None:
        assert isinstance(steam, int), f"Steam should be int, got {type(steam)}"
        assert 1 <= steam <= 5, f"Steam {steam} outside valid range 1-5"


def _test_ssr_valid_star_range(book: StaticTestBook) -> None:
    """Star rating should be None or a float in range 0-5."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    star = ssr["star_rating"]
    if star is not None:
        assert isinstance(star, float), f"Star should be float, got {type(star)}"
        assert 0.0 <= star <= 5.0, f"Star {star} outside valid range 0-5"


def _test_ssr_tags_are_strings(book: StaticTestBook) -> None:
    """All tags returned should be non-empty strings."""
    root = _load_html(book.html_filename)
    ssr = parse_fields_from_ssr_html(root)
    for tag in ssr["tags"]:
        assert isinstance(tag, str) and tag, f"Tag should be non-empty string, got {tag!r}"


def _test_ssr_categories_cover_combined_tags(book: StaticTestBook) -> None:
    """Complete categories must cover every untruncated legacy combined tag."""
    root = _load_html(book.html_filename)
    result = parse_fields_from_ssr_html(root, max_tags=1000)
    categorized_tags = set().union(
        result["general_tags"],
        result["content_warnings"],
        result["geography_tags"],
        result["format_tags"],
    )
    assert set(result["tags"]) <= categorized_tags, (
        f"Combined tags missing from category columns: " f"{set(result['tags']) - categorized_tags}"
    )


def _test_ssr_categories_match_page_categories(book: StaticTestBook) -> None:
    """SSR category columns must mirror Romance.io's visible page groups."""
    root = _load_html(book.html_filename)
    ssr_fields = parse_fields_from_ssr_html(root, max_tags=1000)
    page_categories = parse_tag_categories_from_html(root)
    for key in ("general_tags", "content_warnings", "geography_tags", "format_tags"):
        assert ssr_fields[key] == page_categories[key], f"{key} differs from the page category group"


def _load_local_html(filename: str) -> HtmlElement:
    """Load an HTML file from the local test_data/ directory (plugin-specific edge cases)."""
    test_data_dir = os.path.join(plugin_dir, "test_data")
    filepath = os.path.join(test_data_dir, filename)
    with open(filepath, "rb") as f:
        raw = f.read()
    return fromstring(raw)


# ---------------------------------------------------------------------------
# parse_tags_from_description edge case tests (degenerate HTML inputs)
# ---------------------------------------------------------------------------


def _test_edge_no_meta_description() -> None:
    """parse_tags_from_description returns [] when there is no <meta name='description'>."""
    root = fromstring("<html><head></head><body><p>No meta here.</p></body></html>")
    result = parse_tags_from_description(root)
    assert result == [], f"Expected [], got {result!r}"


def _test_edge_description_without_tagged_as() -> None:
    """parse_tags_from_description returns [] when description omits 'is tagged as' pattern."""
    root = fromstring(
        '<html><head><meta name="description" content="A great book about love and adventure."></head></html>'
    )
    result = parse_tags_from_description(root)
    assert result == [], f"Expected [], got {result!r}"


def _test_edge_description_single_slug() -> None:
    """parse_tags_from_description handles a single slug correctly (no trailing comma)."""
    root = fromstring(
        '<html><head><meta name="description" content="\'A Book\' is tagged as contemporary."></head></html>'
    )
    result = parse_tags_from_description(root)
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) == 1, f"Expected 1 tag, got {result!r}"
    # "contemporary" is a known slug whose display name is the same as the slug
    # (slugs only change when the UI name differs, e.g. "contemporary" -> "Contemporary Romance")
    assert result[0] and isinstance(result[0], str), f"Expected a non-empty string tag, got {result[0]!r}"


def _test_edge_description_whitespace_slugs() -> None:
    """parse_tags_from_description strips whitespace from slugs correctly."""
    root = fromstring(
        "<html><head>"
        '<meta name="description" content="\'A Book\' is tagged as  contemporary ,  historical .">'
        "</head></html>"
    )
    result = parse_tags_from_description(root)
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    # Extra whitespace must not produce empty items or raw-whitespace tags
    assert all(
        isinstance(t, str) and t == t.strip() and t for t in result
    ), f"Tags contain whitespace or empty strings: {result!r}"


def _test_edge_embedded_categories_without_rendered_lists() -> None:
    """The lightweight path can classify tags from tagged_topics without rendered lists."""
    root = fromstring(
        "<html><body><script>"
        'var tagged_topics = {"list":[{"title":"slow burn"}],'
        '"content warnings":[{"title":"grief"}],'
        '"geography":[{"title":"england"}],'
        '"Format":[{"title":"dual pov"}]};'
        "</script></body></html>"
    )
    assert has_tag_category_data(root)
    categories = parse_tag_categories_from_html(root)
    assert categories == {
        "general_tags": ["slow burn"],
        "content_warnings": ["grief"],
        "geography_tags": ["england"],
        "format_tags": ["dual pov"],
    }


def _test_edge_embedded_parser_handles_delimiters_and_invalid_values() -> None:
    """Embedded JSON parsing is not confused by delimiters inside tag titles."""
    root = fromstring(
        "<html><body><script>"
        'var tagged_topics = {"list":['
        '{"title":"contains }; delimiter"},{"title":"   "},{"title":123}],'
        '"content warnings":[],"geography":[],"Format":[]};'
        "</script></body></html>"
    )
    categories = parse_tag_categories_from_html(root)
    assert categories["general_tags"] == ["contains }; delimiter"]

    rendered_root = fromstring(
        '<html><body><ul id="valid-topics-list">'
        '<li class="tagged-topic"><a class="topic">   </a></li>'
        '<li class="tagged-topic"><a class="topic"> slow burn </a></li>'
        "</ul></body></html>"
    )
    rendered_categories = parse_tag_categories_from_html(rendered_root)
    assert rendered_categories["general_tags"] == ["slow burn"]


def _test_edge_empty_embedded_categories_fall_back_to_description() -> None:
    """An empty initialization object must not suppress description categorization."""
    root = fromstring(
        "<html><head>"
        '<meta name="description" content="\'A Book\' is tagged as slow burn, grief, england.">'
        "</head><body><script>var tagged_topics = {};</script></body></html>"
    )
    fields = parse_fields_from_ssr_html(root)
    categorized = set().union(
        fields["general_tags"],
        fields["content_warnings"],
        fields["geography_tags"],
        fields["format_tags"],
    )
    assert set(fields["tags"]) <= categorized
    assert "slow burn" in fields["general_tags"]
    assert "grief" in fields["content_warnings"]
    assert "england" in fields["geography_tags"]


def _test_edge_partial_categories_merge_description_fallback() -> None:
    """A populated general group must not suppress a missing format fallback."""
    root = fromstring(
        "<html><head>"
        '<meta name="description" content="\'A Book\' is tagged as slow burn, length-short.">'
        "</head><body><script>"
        'var tagged_topics = {"list":[{"title":"slow burn"}],'
        '"content warnings":[],"geography":[],"Format":[]};'
        "</script></body></html>"
    )

    fields = parse_fields_from_ssr_html(root)

    assert fields["general_tags"] == ["slow burn"]
    assert fields["format_tags"] == ["Short: 150-249"]


def _test_ssr_category_columns_match_visible_page_groups() -> None:
    """SSR category copies use page groups without changing combined tags."""
    root = fromstring(
        "<html><head>"
        '<meta name="description" content="\'A Book\' is tagged as slow burn.">'
        "</head><body>"
        '<ul id="valid-topics-list">'
        '<li class="tagged-topic"><a class="topic">slow burn</a></li>'
        '<li class="tagged-topic"><a class="topic">community favorite</a></li>'
        "</ul>"
        "<script>"
        'var tagged_topics = {"list":['
        '{"title":"slow burn"},{"title":"community favorite"}],'
        '"content warnings":[],"geography":[],"Format":[]};'
        "</script></body></html>"
    )

    fields = parse_fields_from_ssr_html(root)

    assert fields["tags"] == ["slow burn"]
    assert fields["general_tags"] == ["slow burn", "community favorite"]


def _test_edge_format_category_order_is_stable() -> None:
    """Overlapping rendered selectors must deduplicate without reordering tags."""
    root = fromstring(
        '<html><body><ul id="valid-topics-Format">'
        '<li class="tagged-topic"><a class="topic">audiobook</a></li>'
        '<li class="tagged-topic"><a class="topic">dual pov</a></li>'
        "</ul></body></html>"
    )
    categories = parse_tag_categories_from_html(root)
    assert categories["format_tags"] == ["audiobook", "dual pov"]


# ---------------------------------------------------------------------------
# parse_fields_from_ssr_html edge case tests (using local test_data/ files)
# ---------------------------------------------------------------------------


def _test_edge_no_ratings_star_is_none() -> None:
    """parse_fields_from_ssr_html on a zero-ratings page returns star_rating=None."""
    root = _load_local_html("no_ratings_source.html")
    result = parse_fields_from_ssr_html(root)
    assert (
        result["star_rating"] is None
    ), f"Expected star_rating=None for a zero-ratings page, got {result['star_rating']}"


def _test_edge_no_ratings_count_is_zero() -> None:
    """parse_fields_from_ssr_html on a zero-ratings page returns rating_count=0."""
    root = _load_local_html("no_ratings_source.html")
    result = parse_fields_from_ssr_html(root)
    assert (
        result["rating_count"] == 0 or result["rating_count"] is None
    ), f"Expected rating_count=0 for a zero-ratings page, got {result['rating_count']}"


def _test_edge_no_ratings_tags_still_work() -> None:
    """parse_fields_from_ssr_html on a zero-ratings page still returns tags from description."""
    root = _load_local_html("no_ratings_source.html")
    result = parse_fields_from_ssr_html(root)
    # no_ratings_source.html description has multiple slugs - at least one should map
    assert isinstance(result["tags"], list), "tags must be a list"
    assert len(result["tags"]) > 0, "Expected tags from meta description even when book has no ratings"


# ---------------------------------------------------------------------------
# Edge case test runner
# ---------------------------------------------------------------------------


def run_edge_case_tests() -> None:
    print(f"\n{'=' * 70}")
    print("EDGE CASE TESTS (degenerate HTML inputs)")
    print("=" * 70)

    _run("no <meta name='description'> -> []", _test_edge_no_meta_description)
    _run("description without 'is tagged as' -> []", _test_edge_description_without_tagged_as)
    _run("description with single slug -> 1 tag", _test_edge_description_single_slug)
    _run("description with padded whitespace -> stripped tags", _test_edge_description_whitespace_slugs)
    _run("embedded tagged_topics -> categorized tags", _test_edge_embedded_categories_without_rendered_lists)
    _run(
        "embedded parser handles delimiters and invalid values",
        _test_edge_embedded_parser_handles_delimiters_and_invalid_values,
    )
    _run(
        "empty embedded categories fall back to description",
        _test_edge_empty_embedded_categories_fall_back_to_description,
    )
    _run(
        "partial categories merge description fallback",
        _test_edge_partial_categories_merge_description_fallback,
    )
    _run("SSR categories mirror visible page groups", _test_ssr_category_columns_match_visible_page_groups)
    _run("format tags retain rendered order", _test_edge_format_category_order_is_stable)
    _run("no-ratings page: star_rating is None", _test_edge_no_ratings_star_is_none)
    _run("no-ratings page: rating_count is 0", _test_edge_no_ratings_count_is_zero)
    _run("no-ratings page: tags still returned from description", _test_edge_no_ratings_tags_still_work)


def run_all_tests() -> None:
    print("\n" + "=" * 70)
    print("SSR HTML FIELD PARSING TESTS (romanceio_fields)")
    print("Tests parse_tags_from_description() and parse_fields_from_ssr_html()")
    print("=" * 70)

    for book in STATIC_TEST_BOOKS:
        print(f"\n{'=' * 70}")
        print(f"Book: {book.name} ({book.romanceio_id})")
        print("=" * 70)

        print("\n  [parse_tags_from_description]")
        _run(f"{book.name}: description tags non-empty", lambda b=book: _test_description_tags_non_empty(b))
        _run(
            f"{book.name}: description tags are display names",
            lambda b=book: _test_description_tags_are_display_names(b),
        )
        _run(f"{book.name}: description tags match JSON API", lambda b=book: _test_description_tags_match_json_api(b))
        _run(
            f"{book.name}: description tags ⊆ Chrome tags",
            lambda b=book: _test_description_tags_subset_of_chrome_tags(b),
        )
        _run(
            f"{book.name}: description tag count == JSON count", lambda b=book: _test_description_tags_minimum_count(b)
        )
        _run(f"{book.name}: sample tags present in SSR tags", lambda b=book: _test_description_tags_sample_present(b))
        _run(
            f"{book.name}: no steam text in description tags", lambda b=book: _test_description_tags_no_steam_leaked(b)
        )

        print("\n  [parse_fields_from_ssr_html]")
        _run(f"{book.name}: SSR returns correct dict keys", lambda b=book: _test_ssr_returns_dict(b))
        _run(f"{book.name}: SSR steam == Chrome steam", lambda b=book: _test_ssr_steam_rating_matches_chrome(b))
        _run(f"{book.name}: SSR star ≈ Chrome star", lambda b=book: _test_ssr_star_rating_matches_chrome(b))
        _run(f"{book.name}: SSR count == Chrome count", lambda b=book: _test_ssr_rating_count_matches_chrome(b))
        _run(f"{book.name}: SSR tags == JSON API tags", lambda b=book: _test_ssr_tags_match_json_api(b))
        _run(f"{book.name}: SSR tags ⊆ Chrome tags", lambda b=book: _test_ssr_tags_subset_of_chrome(b))
        _run(f"{book.name}: max_tags limiting works", lambda b=book: _test_ssr_max_tags_limiting(b))
        _run(f"{book.name}: no steam text in SSR tags", lambda b=book: _test_ssr_no_steam_text_in_tags(b))
        _run(f"{book.name}: steam in range 1-5 or None", lambda b=book: _test_ssr_valid_steam_range(b))
        _run(f"{book.name}: star in range 0-5 or None", lambda b=book: _test_ssr_valid_star_range(b))
        _run(f"{book.name}: all tags are non-empty strings", lambda b=book: _test_ssr_tags_are_strings(b))
        _run(
            f"{book.name}: categories cover combined tags",
            lambda b=book: _test_ssr_categories_cover_combined_tags(b),
        )
        _run(
            f"{book.name}: SSR categories match page categories",
            lambda b=book: _test_ssr_categories_match_page_categories(b),
        )

    run_edge_case_tests()

    print(f"\n{'=' * 70}")
    print(f"RESULTS: {len(_passed)} passed, {len(_failed)} failed")
    print("=" * 70)

    if _failed:
        print("\nFailed tests:")
        for t in _failed:
            print(f"  ❌ {t}")
        sys.exit(1)
    else:
        print("\n✓ All SSR field parsing tests passed!")


if __name__ == "__main__":
    run_all_tests()
