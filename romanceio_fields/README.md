# Romance.io Fields - Custom Columns Plugin for Calibre

> **For user-facing install and usage instructions, see the [main README](../README.md).**

A Calibre interface action plugin that fetches Romance.io-specific data (steam rating, star rating, vote count, tags) and writes them into user-configured custom columns.

## What This Plugin Does

1. Searches [Romance.io](https://www.romance.io/) for books matching the title and author and, if found, stores the book's Romance.io ID
2. Loads each book's Romance.io detail page and parses HTML to extract steam rating, star rating, vote count, and community tags
3. Filters tags by maximum count setting
4. Writes values into the user-configured custom columns
5. Optionally prompts before saving

## Configuration

**Preferences > Plugins > Romance.io Fields > Customize plugin**

| Setting | Default | Description |
|---|---|---|
| Refresh existing fields | ✓ checked | Re-download all fields even if already set (ID is never overwritten) |
| Prompt to save | ☐ unchecked | Show confirmation dialog before writing to library |
| Get tags directly from website HTML (slower) | ☐ unchecked | Fetch tags from the Romance.io website instead of the JSON API for exact tag matching (slower, requires browser) |
| Steam column | - | Lookup name of your steam rating column |
| Tags column | - | Lookup name of your tags column |
| Maximum tags | 50 | Cap on number of tags downloaded per book |
| Star rating column | - | Lookup name of your star rating column |
| Rating count column | - | Lookup name of your vote count column |

## Custom Columns Setup

Users must create custom columns before the plugin can write to them.

1. *Preferences > Add your own columns*
2. Click "Add custom column" and create:

| Field | Lookup Name | Column Type | Additional Setup | Description |
|-------|-------------|-------------|------------------|-------------|
| Romance.io ID | `#romanceio` | Column built from other columns | Template `{identifiers:select(romanceio)}` and sort by `Text` | ID used in Romance.io URL. Show this column as an indicator of whether the book was able to be found on Romance.io. |
| Romance.io Steam Rating | `#romiosteam` | Integers | | Values 1-5 based on [Romance.io steam ratings](https://www.romance.io/steamrating) |
| Romance.io Stars | `#romiostars` | Floating point numbers | With 2 decimals | Star rating from Romance.io user votes |
| Romance.io Vote Count | `#romiovotes` | Integer | | Total number of star ratings for a book on Romance.io |
| Romance.io Tags | `#romiotags` | Comma-separated text, like tags | | User-sourced tags from Romance.io |

> **Note:** You can use any field and lookup names you prefer - you'll configure them in the plugin settings.

Additional customization settings:
- **Refresh existing fields when downloading from Romance.io** - When checked (default), all configured fields are updated with the latest data from Romance.io, even if they already have values. The Romance.io ID is never overwritten to avoid unnecessary searches. To change or re-download the ID, manually delete it from the book's identifiers. Uncheck if you have manually edited field values and don't want them overwritten.
- **Prompt to save fields after downloading** - At the end of the download process, user can confirm if they would like to add the downloaded metadata for all selected books
- **Maximum tags to download** - Maximum number of tags to download (default: 50)
- **Minimum tag votes** - Minimum user votes for a tag to be included in the download (default: 0)
- **Prioritize website (HTML) for tags instead of JSON API** - When checked, the plugin fetches data directly from the Romance.io website instead of the JSON API. This ensures tags match exactly what you see on the website - without this option, the JSON API is used first (faster), but some tags may be missing or slightly different compared to what appears on the site. Requires opening a browser window and is slower than the default JSON API.

## Usage

### Download Fields

1. Select one or more books in your library
2. Click the Romance.io plugin button
3. The plugin will:
   - Check if the book is already associated with a Romance.io identifier
   - If not found, search Romance.io by title/author
   - Download the selected fields (steam rating, star rating, vote count, tags)
   - Update your custom columns with the downloaded values

> **Note:** Browser windows may open during the process - just ignore them and let the plugin work. Don't close them or click anything.

### Updating Existing Books

To refresh metadata for books that already have Romance.io IDs stored:

1. Select all the books you want to update
2. Click the Romance.io plugin button
3. This update will run faster than the initial download because it skips the search step and goes directly to each book's page on Romance.io to re-scan for the latest metadata (tags, ratings, etc.)

This is useful for:
- Getting newly added tags from the Romance.io community
- Updating star ratings and vote counts as more users rate books
- Refreshing data after Romance.io updates

### Menu Options

Right-click on selected books to access:
- **Download fields for selected book(s)** - Download all configured fields
- **Customize plugin** - Open plugin settings

## Requirements

**Romance.io Identifier:**
The plugin needs to know the Romance.io ID for each book. Either:
1. Use the [Romance.io](../romanceio/README.md) metadata plugin to set identifiers, or
2. The plugin will search for the book automatically using title/author

## How It Works

This plugin:
1. Gets the Romance.io ID from the book's identifiers or searches for it
2. Uses SeleniumBase to load the book's detail page (bypassing Cloudflare)
3. Parses the HTML to extract steam rating, star rating, rating count, and tags
4. Filters and formats tags based on your settings
5. Updates your custom columns with the downloaded data

## Tag Filtering

Tags are filtered by the number of users who have voted for them:
- **Min Tag Votes = 0** - All tags included
- **Min Tag Votes = 10** - Only tags with 10+ user votes

Tags are also limited by the **Max Tags** setting and ordered by vote count (most popular first). If a book has 15 tags and **Max Tags** is set to 10, the plugin will only download the 10 highest-voted tags for that book.

## Building

```bash
cd romanceio_fields && ./build.sh
```

`build.sh` runs `setup_deps.sh` (vendors dependencies), then `build.py` (copies `common/` files with rewritten imports, creates `Romance.io Fields.zip`).

## Testing

Run from inside the `romanceio_fields/` directory after building.

**Smoke test** (fast, no browser):
```bash
calibre-debug -e __init__.py
```

**JSON tests** (fast, offline - no browser):
```bash
calibre-debug test_json_parsing.py          # Star rating, steam, vote count, tags from JSON
calibre-debug test_json_search_matching.py  # Best-match selection from JSON search results
calibre-debug test_tag_mapping.py           # Display-name consistency, topics-page HTML extraction
calibre-debug test_tag_slug_conversion.py   # Slug-to-display-name conversion (copied from common/)
calibre-debug test_html_sanitizer.py        # sanitize_html_for_lxml() strips XML 1.0 illegal chars (copied from common/)
```

**HTML unit tests** (offline, uses static HTML from `common_romanceio_static_test_data/`):
```bash
calibre-debug test_html_fields_parsing.py
calibre-debug test_json_html_parse_matches.py
```

**Integration tests** (slow, require internet and browser):
```bash
calibre-debug test_json_download.py             # Live JSON API fetch and field validation
calibre-debug test_html_fields_download.py      # Live HTML fetch and field validation
calibre-debug test_json_html_parse_matches.py -- --live         # 1 live book
calibre-debug test_json_html_parse_matches.py -- --live=<id>    # Specific book ID
```

> `test_json_search_matching.py`, `test_tag_slug_conversion.py`, and `test_html_sanitizer.py` are copied from `common/` during build.

## Tag Filtering Detail

Tags from Romance.io have vote counts attached. The plugin:
1. Filters out tags below `min_tag_votes`
2. Sorts remaining tags by vote count (descending)
3. Takes the top `max_tags`

This means popular/agreed-upon tags are preferred when capping.

## Troubleshooting

**No Romance.io ID found, wrong book matched, or your title/author intentionally differs from Romance.io:**
- Verify that the title and author in Calibre match Romance.io exactly, delete any incorrect `romanceio` identifier in the book's `Ids` field, and then try again
- If your library uses a different edition name or author spelling, or you've intentionally renamed the book, the automatic search won't work, but you can still link the book manually
- Find the book on [Romance.io](https://www.romance.io) and open its **book detail page** (not the series page - the URL should contain `/books/`). Copy the ID from the URL (e.g. `5484ecd47a5936fb0405756c` from `https://romance.io/books/5484ecd47a5936fb0405756c/...`), and set it manually in the `Ids` field as: `romanceio:5484ecd47a5936fb0405756c`

![Calibre "Edit metadata" menu emphasizing the "Ids" field where users can manually enter the Romance.io ID](../images/Edit%20metadata%20-%20set%20ID.png)

**Fields not updating:**
- Check that your custom columns are created and mapped correctly in plugin settings
- Verify the lookup names match exactly (case-sensitive)

**Chrome is not installed ("Chrome is not installed - HTML metadata fallback is unavailable"):**
- The plugin uses Chrome to load Romance.io pages (required to bypass Cloudflare)
- Install Chrome from [google.com/chrome](https://www.google.com/chrome/)
- Without Chrome, the plugin cannot fetch data
- **Linux with Chrome installed as a flatpak:** the plugin can find Chrome automatically, but if Calibre is also a flatpak you need to run this once in a terminal and restart Calibre:
  ```
  flatpak override --user com.calibre_ebook.calibre --filesystem=host
  ```

**Slow performance:**
- Expected: 10-30 seconds per book - browser automation is required to bypass Cloudflare

## Support

Report issues on [GitHub Issues](https://github.com/plain-cover/calibre_plugins/issues). Include:
- Exact **title and author in Calibre**, and the **expected Romance.io URL**
- **Which plugin** - if the issue happened when clicking the magnifying glass icon, then it is due to the **Romance.io Fields** plugin; if it happened during a metadata download, it is the **Romance.io** plugin
- **Calibre version** - shown in the bottom-left of the Calibre window, or via **Help > About Calibre**
- **Plugin version** - **Preferences > Plugins**, find the plugin (Romance.io Fields), note the version (e.g. 1.0.0)
- **Error logs** - if a job fails, a pop-up appears with the error. Otherwise, click the job count in the bottom-right of Calibre, select the failed job, and click **Show job details**. Copy and paste the output.

For more verbose logs, right-click the **Preferences** button (gear icon) and choose **Restart in debug mode**.
