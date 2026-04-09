# Static Test Data for Calibre Plugins

**Centralized static test data used by both `romanceio` and `romanceio_fields` plugins for offline testing.**

## Quick Summary

- **Location:** `common/common_romanceio_static_test_data/` (source of truth)
- **Build:** Files are automatically copied to both plugins during build
- **Usage:** Import from `common_romanceio_static_test_data` module
- **Updating:** Use `update_static_test_data.py` script (see below)

## ⚠️ CRITICAL: Keep JSON & HTML Synchronized

**When updating test data, you MUST update both JSON and HTML files for the same book at the same time.**

## Why Keep Test Data Here?

We keep test data here instead of duplicating it in each Romance.io plugin because:

- All tests use the same source files (single source of truth, no drift between plugins)
- Update script refreshes files from live site and keeps JSON and HTML versions of Romance.io data synchronized
- Adding new books only requires updating one location
- Build process automatically copies files to plugins
- Git tracks all changes for debugging regressions

If files become out of sync, tests that compare JSON and HTML parsing will fail because they expect matching:
- Star ratings
- Rating counts
- Steam ratings
- Tag lists (substantial overlap)

**Always use the update script** (`update_static_test_data.py --update <id>`) **to keep files synchronized.** Manual updates require capturing JSON and HTML snapshots at the exact same time.

## File Naming Convention

Files are named using the Romance.io book ID:
- Book detail JSON: `<romanceio_id>.json`
- Book detail HTML: `<romanceio_id>.html`
- Search results JSON: `search_<romanceio_id>.json`
- Search results HTML: `search_<romanceio_id>.html`
- Author JSON: `author_<author_id>.json`

## Current Test Books

**Pride and Prejudice** by Jane Austen
- ID: `5484ecd47a5936fb0405756c`
- Files: book JSON/HTML, search JSON/HTML, author JSON

**Funny Story** by Emily Henry
- ID: `65b604fa00d361e53f20ecfb`
- Files: book JSON/HTML, search JSON/HTML, author JSON

## Adding a New Test Book

### Automated Method (Recommended)

Use the update script to download all files automatically:

```bash
# 1. Build the romanceio plugin first (required for browser automation)
cd romanceio && ./build.sh

# 2. Download files for the new book
calibre-debug -e ../common/update_static_test_data.py -- --add <romanceio_id>
```

**Requirements:**
- Must run from `romanceio/` directory after building
- Browser window will appear briefly (normal behavior for HTML fetching)

### After Downloading

**1. Add book metadata** to `common/common_romanceio_static_test_data.py`:

Edit the `STATIC_TEST_BOOKS` list and add:

```python
StaticTestBook(
    name="Book Display Name",
    romanceio_id="<romanceio_id>",
    title="Book Title",
    authors=["Author Name"],
    author_ids={"Author Name": "<author_id>"},
    star_rating=4.5,  # Approximate expected rating
    steam_rating=2,  # Expected steam rating (0-5)
    rating_count=1000,  # Approximate expected count
    expected_tag_count=30,  # Approximate number of tags
    sample_tags=["tag1", "tag2", "tag3"],  # Sample tags to verify
    pubdate_year=2024,  # Publication year (optional)
    series_info=("Series Name", 1),  # (series name, position) or None
),
```

**2. Rebuild both plugins:**

```bash
cd romanceio && ./build.sh
cd ../romanceio_fields && ./build.sh
```

**3. Run tests to verify:**

```bash
# In romanceio plugin
cd romanceio
calibre-debug test_json_parsing.py
calibre-debug test_json_search_matching.py
calibre-debug test_html_search_parsing.py
calibre-debug test_json_html_parse_matches.py  # also runs live tests

# In romanceio_fields plugin
cd ../romanceio_fields
calibre-debug test_json_parsing.py
calibre-debug test_json_search_matching.py
calibre-debug test_html_fields_parsing.py
calibre-debug test_json_html_parse_matches.py  # also runs live tests
```

## Updating Existing Test Data

Refresh test data when Romance.io changes HTML/JSON format or to get current ratings:

```bash
# 1. Build romanceio plugin first
cd romanceio && ./build.sh

# 2. Update all books
calibre-debug -e ../common/update_static_test_data.py -- --all

# Or update specific book
calibre-debug -e ../common/update_static_test_data.py -- --update <romanceio_id>
```

**What gets updated:**
- Book search JSON and HTML
- Book details JSON and HTML
- Author JSON

**After updating:**
1. Review: `git diff common/common_romanceio_static_test_data/`
2. Rebuild both plugins
3. Run tests to verify
4. Commit if tests pass

**Troubleshooting:**
- **"Empty HTML content"** - Run `./build.sh` first, execute from `romanceio/` directory
- **"Cannot import from plugin"** - Must run from `romanceio/` after building
- **Empty HTML files** - Restore: `git checkout common/common_romanceio_static_test_data/*.html`

## Usage in Code

Access static test books and load their files:

```python
from common.common_romanceio_static_test_data import (
    STATIC_TEST_BOOKS,
    load_static_json_file,
    load_static_html_file,
    get_static_book_by_name,
    get_static_book_by_id,
)

# Iterate all static books
for book_data in STATIC_TEST_BOOKS:
    print(book_data.name, book_data.romanceio_id)
    json_data = load_static_json_file(book_data.json_filename)
    html_data = load_static_html_file(book_data.html_filename)

# Get specific book
book = get_static_book_by_name("Pride and Prejudice")
if book:
    json_data = load_static_json_file(book.json_filename)
    html_data = load_static_html_file(book.html_filename)
    search_json = load_static_json_file(book.search_json_filename)
    search_html = load_static_html_file(book.search_html_filename)
```
