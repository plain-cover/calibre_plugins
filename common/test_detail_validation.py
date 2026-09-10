"""Tests for validating fetched detail payloads before fallback stops."""

from common.common_romanceio_fetch_helper import parse_html_from_selenium
from common.common_romanceio_validation import (
    is_usable_book_detail_html,
    is_usable_book_detail_json,
)

BOOK_ID = "5484ecd47a5936fb0405756c"


def test_json_detail_requires_matching_identity_title_and_authors():
    valid = {
        "_id": BOOK_ID,
        "info": {"title": "Pride and Prejudice", "numRating": 0},
        "authors": [{"name": "Jane Austen"}],
    }

    assert is_usable_book_detail_json(valid, BOOK_ID)
    assert not is_usable_book_detail_json({**valid, "_id": "64aae9ea0f498c040bf904ad"}, BOOK_ID)
    assert not is_usable_book_detail_json({**valid, "info": {"numRating": 10}}, BOOK_ID)
    assert not is_usable_book_detail_json({**valid, "authors": []}, BOOK_ID)
    assert not is_usable_book_detail_json("not a dict", BOOK_ID)


def test_html_detail_requires_parsable_identity_and_stats_structure():
    valid = parse_html_from_selenium("""
        <html><body><div id="main">
          <div class="book-info">
            <h1>Pride and Prejudice</h1>
            <h2 class="author">Jane Austen</h2>
          </div>
          <div id="book-stats"><span>1,000 ratings</span></div>
        </div></body></html>
        """)
    interstitial = parse_html_from_selenium(
        "<html><head><script>const expected = 'book-stats';</script></head><body>Please wait</body></html>"
    )

    assert is_usable_book_detail_html(valid)
    assert not is_usable_book_detail_html(interstitial)


def test_html_detail_rejects_missing_title_author_or_stats():
    templates = (
        '<div id="main"><div class="book-info"><h2 class="author">Author</h2></div><div id="book-stats"/></div>',
        '<div id="main"><div class="book-info"><h1>Title</h1></div><div id="book-stats"/></div>',
        '<div id="main"><div class="book-info"><h1>Title</h1><h2 class="author">Author</h2></div></div>',
    )

    for html in templates:
        assert not is_usable_book_detail_html(parse_html_from_selenium(html))
