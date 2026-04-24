# Romance.io - Metadata Source Plugin for Calibre

> **For user-facing install and usage instructions, see the [main README](../README.md).**

A Calibre metadata source plugin that searches Romance.io by title and author, stores the Romance.io book ID as a Calibre identifier, and optionally downloads fields like cover image, series, tags, star rating, description, and date published.

## What This Plugin Does

1. Searches [Romance.io](https://www.romance.io/) for books matching the title and author
2. Parses search results to find the best match
3. Stores the Romance.io ID in the book's `romanceio` identifier field
4. Returns the cover URL so Calibre can offer it in cover selection, and additional fields like series, description, star rating, tags, and date published
5. Optionally maps Romance.io genre tags to Calibre tags via a configurable mapping table

The stored `romanceio` identifier is the key that the companion [Romance.io Fields](../romanceio_fields/README.md) plugin can use to fetch ratings and tags.

## Configuration

**Preferences > Metadata download > Romance.io > Configure selected source**

- **Romance.io tag to Calibre tag mappings** - Controls how Romance.io tags are imported into Calibre's Tags field. Use the green "+" and red "-" buttons to add or remove mappings. Create one row for each Romance.io tag you want to map to one or more Calibre tags. The text you enter for the Romance.io tag must match how the tag looks on the website exactly. Any Romance.io tags that are not mapped will be ignored.

  ![Screenshot of the Configure Metadata download dialog with the "Filter and map Romance.io tags to calibre tags" checkbox checked](../images/Configure%20Metadata%20download.png)

  To get all tropes and genres as separate Calibre tags, uncheck **"Filter and map Romance.io tags to Calibre tags"**:

  - **Checked (default):** Only tags listed in the mapping table are imported. Each Romance.io tag maps to one or more Calibre tags of your choosing. Tags not in the table are dropped.
  - **Unchecked:** All Romance.io tags are imported as individual Calibre tags, with no filtering or renaming. Use this if you want to import every Romance.io tag for each book.

  ![Configure Metadata download dialog showing the "Filter and map Romance.io tags to Calibre tags" checkbox unchecked](../images/Uncheck%20map%20tags.png)

  With the box unchecked, the metadata download will import all tags from Romance.io as Calibre tags:

  ![Metadata download result showing all Romance.io tags as individual Calibre tags](../images/Uncheck%20map%20tags%20result.png)

## Building

```bash
cd romanceio && ./build.sh
```

`build.sh` runs `setup_deps.sh` (vendors dependencies via pip into the plugin folder), then `build.py` (copies `common/` files with rewritten imports, creates `Romance.io.zip`).

## Testing

Run from inside the `romanceio/` directory after building.

**JSON tests** (fast, offline - no browser):
```bash
calibre-debug test_json_parsing.py          # Title, authors, cover, ID from JSON
calibre-debug test_json_search_matching.py  # Best-match selection from JSON search results
calibre-debug test_tag_mapping.py           # Genre mapping pipeline: slugs -> display names -> Calibre tags
calibre-debug test_tag_slug_conversion.py   # Slug-to-display-name conversion (copied from common/)
calibre-debug test_html_sanitizer.py        # sanitize_html_for_lxml() strips XML 1.0 illegal chars (copied from common/)
```

**HTML tests** (offline, uses static HTML files in `common_romanceio_static_test_data/`):
```bash
calibre-debug test_html_search_parsing.py
calibre-debug test_json_html_parse_matches.py
```

**Integration tests** (slow, require internet and browser):
```bash
calibre-debug -e __init__.py                    # Smoke test + full functional tests with live searches
calibre-debug test_cover_download.py            # Live cover downloads
calibre-debug test_json_html_parse_matches.py -- --live         # 1 live book
calibre-debug test_json_html_parse_matches.py -- --live=<id>    # Specific book ID
```

> `test_json_search_matching.py`, `test_tag_slug_conversion.py`, and `test_html_sanitizer.py` are copied from `common/` during build.

## Troubleshooting

**Search returns no results, wrong book matched, or your title/author intentionally differs from Romance.io:**
- Verify that the title and author in Calibre match Romance.io exactly, delete any incorrect `romanceio` identifier in the book's `Ids` field, and then try again
- If your library uses a different edition name or author spelling, or you've intentionally renamed the book, the automatic search won't work, but you can still link the book manually
- Find the book on [Romance.io](https://www.romance.io) and open its **book detail page** (not the series page - the URL should contain `/books/`). Copy the ID from the URL (e.g. `5484ecd47a5936fb0405756c` from `https://romance.io/books/5484ecd47a5936fb0405756c/...`), and set it manually in the `Ids` field as: `romanceio:5484ecd47a5936fb0405756c`

![Calibre "Edit metadata" menu emphasizing the "Ids" field where users can manually enter the Romance.io ID](../images/Edit%20metadata%20-%20set%20ID.png)

**Chrome is not installed ("Chrome is not installed - HTML metadata fallback is unavailable"):**
- The plugin uses Chrome to scrape Romance.io as a fallback when the JSON API is unavailable
- Install Chrome from [google.com/chrome](https://www.google.com/chrome/) to enable this fallback
- Without Chrome, metadata download will still work when the JSON API is available

**Browser/chromedriver errors:**
- Ensure Chrome is installed ([google.com/chrome](https://www.google.com/chrome/))
- Check your internet connection
- Check logs for errors

## Support

Report issues on [GitHub Issues](https://github.com/plain-cover/calibre_plugins/issues). Include:
- Exact **title and author in Calibre**, and the **expected Romance.io URL**
- **Which plugin** - if the issue happened during a metadata download (right-click > **Download metadata**), then it is from the **Romance.io** plugin; if the issue happened when clicking the magnifying glass icon, then it is due to the **Romance.io Fields** plugin
- **Calibre version** - shown in the bottom-left of the Calibre window, or via **Help > About Calibre**
- **Plugin version** - **Preferences > Plugins**, find the plugin (Romance.io), note the version (e.g. 1.0.0)
- **Error logs** - if a job fails, a pop-up appears with the error. Otherwise, click the job count in the bottom-right of Calibre, select the failed job, and click **Show job details**. Copy and paste the output.

For more verbose logs, right-click the **Preferences** button (gear icon) and choose **Restart in debug mode**.
