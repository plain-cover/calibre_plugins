# Romance.io - Metadata Source Plugin for Calibre

> **For user-facing install and usage instructions, see the [main README](../README.md).**

A Calibre metadata source plugin that searches Romance.io by title and author, stores the Romance.io book ID as a Calibre identifier, and optionally downloads fields like cover image, series, tags, and date published.

## What This Plugin Does

1. Searches [Romance.io](https://www.romance.io/) for books matching the title and author
2. Parses search results to find the best match
3. Stores the Romance.io ID in the book's `romanceio` identifier field
4. Returns the cover URL so Calibre can offer it in cover selection, and additional fields like series and date published
5. Optionally maps Romance.io genre tags to Calibre tags via a configurable mapping table

The stored `romanceio` identifier is the key that the companion [Romance.io Fields](../romanceio_fields/README.md) plugin can use to fetch ratings and tags.

## Configuration

**Preferences > Metadata download > Romance.io > Configure selected source**

- **Romance.io tag to Calibre tag mappings** - Map Romance.io genre tag slugs to Calibre tag values using the configurable table. Tags not present in the mapping are not imported.

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

> `test_json_search_matching.py` and `test_tag_slug_conversion.py` are copied from `common/` during build.

## Troubleshooting

**Search returns no results, wrong book matched, or your title/author intentionally differs from Romance.io:**
- Verify that the title and author in Calibre match Romance.io exactly, delete any incorrect `romanceio` identifier in the book's `Ids` field, and then try again
- If your library uses a different edition name or author spelling, or you've intentionally renamed the book, the automatic search won't work, but you can still link the book manually
- Find the book on [Romance.io](https://www.romance.io) and open its **book detail page** (not the series page - the URL should contain `/books/`). Copy the ID from the URL (e.g. `5484ecd47a5936fb0405756c` from `https://romance.io/books/5484ecd47a5936fb0405756c/...`), and set it manually in the `Ids` field as: `romanceio:5484ecd47a5936fb0405756c`

![Calibre "Edit metadata" menu emphasizing the "Ids" field where users can manually enter the Romance.io ID](../images/Edit%20metadata%20-%20set%20ID.png)

**Browser/chromedriver errors:**
- Check your internet connection
- Check logs for errors

## Support

Report issues on [GitHub Issues](https://github.com/plain-cover/calibre_plugins/issues). Include:
- Exact title and author in Calibre, and the expected Romance.io URL
- **Calibre version** - shown in the bottom-left of the Calibre window, or via **Help > About Calibre**
- **Plugin version** - **Preferences > Plugins**, find the plugin (Romance.io), note the version (e.g. 1.0.0)
- **Error logs** - if a job fails, a pop-up appears with the error. Otherwise, click the job count in the bottom-right of Calibre, select the failed job, and click **Show job details**. Copy and paste the output.

For more verbose logs, right-click the **Preferences** button (gear icon) and choose **Restart in debug mode**.
