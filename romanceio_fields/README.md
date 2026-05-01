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
| Get tags directly from website (slower but includes additional community tags) | ☐ unchecked | Try the browser first to get the full JS-rendered tag set including community-voted tags; falls back to the JSON API and lightweight HTTP fetch if the browser is unavailable |
| Steam column | - | Lookup name of your steam rating column |
| Tags column | - | Lookup name of your tags column |
| Maximum tags | 50 | Cap on number of tags downloaded per book |
| Star rating column | - | Lookup name of your star rating column |
| Rating count column | - | Lookup name of your vote count column |

## Custom Columns Setup

The plugin writes data from [Romance.io](https://romance.io) into custom columns in Calibre. You need to create the columns yourself first so we have a place to put the data. Each field (Romance.io ID, steam rating, star rating, vote count, tags) needs its own column with the right column type so Calibre knows how to store and sort the data.

**Step 1 - Create custom columns**

Go to **Preferences > Add your own columns** and add a new column for each field you want. You don't have to create all of them - only the columns you want to be able to sort and filter on. Here's what each column should look like when you're creating it:

Romance.io ID:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io ID column](../images/Add%20custom%20column%20-%20ID.png)

Romance.io Steam Rating:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Steam Rating column](../images/Add%20custom%20column%20-%20steam.png)

Romance.io Stars:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Stars column](../images/Add%20custom%20column%20-%20stars.png)

Romance.io Vote Count:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Vote Count column](../images/Add%20custom%20column%20-%20votes.png)

Romance.io Tags:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Tags column](../images/Add%20custom%20column%20-%20tags.png)

Here's a reference table for creating each column. Lookup names can be anything you choose - you'll map them to your chosen names in Step 2.

| Field | Lookup Name | Column Type | Additional Setup | Description |
|-------|-------------|-------------|------------------|-------------|
| Romance.io ID | `#romanceio` | Column built from other columns | Template `{identifiers:select(romanceio)}` and sort by `Text` | ID used in Romance.io URL. Show this column as an indicator of whether the book was able to be found on Romance.io. |
| Romance.io Steam Rating | `#romiosteam` | Integers | | Values 1-5 based on [Romance.io steam ratings](https://www.romance.io/steamrating) |
| Romance.io Stars | `#romiostars` | Floating point numbers | With 2 decimals | Star rating from Romance.io user votes |
| Romance.io Vote Count | `#romiovotes` | Integers | | Total number of star ratings for a book on Romance.io |
| Romance.io Tags | `#romiotags` | Comma-separated text, like tags | | User-sourced tags from Romance.io |

**Step 2 - Map columns in plugin settings**

Click the dropdown arrow next to the Romance.io icon and select **Customize plugin**:

![Screenshot of the main toolbar in Calibre with the Romance.io Fields plugin dropdown selected](../images/Main%20toolbar%20icon.png)

You can also open **Preferences > Plugins**, find "Romance.io Fields", and click **Customize plugin**.

In the customization menu, map each field to the lookup name of the column you created:

![Calibre "Customize Romance.io Fields" menu showing the mapping of fields to column lookup names](../images/Customize%20plugin%20field%20mappings.png)

Additional customization settings:
- **Refresh existing fields when downloading from Romance.io** - When checked (default), all configured fields are updated with the latest data from Romance.io, even if they already have values. The Romance.io ID is never overwritten to avoid unnecessary searches. To change or re-download the ID, manually delete it from the book's identifiers. Uncheck if you have manually edited field values and don't want them overwritten.
- **Prompt to save fields after downloading** - At the end of the download process, user can confirm if they would like to add the downloaded metadata for all selected books
- **Maximum tags to download** - Maximum number of tags to download (default: 50)
- **Get tags directly from website (slower but includes additional community tags)** - When checked, the plugin tries to open the Romance.io page in a browser first. This gives you the full community-voted tag set that is only available after JavaScript renders the page. If the browser is unavailable or fails, the plugin automatically falls back to the JSON API and then to a lightweight HTTP fetch, so you still get metadata even without Chrome. Unchecked (default): the plugin goes straight to the JSON API, then lightweight HTTP, then browser - which is faster and works without Chrome for most users.
  > **Why do my tags look different from what I see on Romance.io?**
  > Romance.io displays two layers of tags: a core set (tropes, genres, etc.) stored in their database and returned by the API, and additional community-voted tags injected into the page by JavaScript after it loads. The default fast fetch (JSON API / lightweight HTTP) retrieves only the core set. To get the community tags too, enable this option - but be aware it requires Chrome and is slower since a browser window will have to open for each book.

## Usage

### Download Fields

1. Select one or more books in your library
2. Click the Romance.io plugin button
3. The plugin will:
   - Check if the book is already associated with a Romance.io identifier
   - If not found, search Romance.io by title/author
   - Download the selected fields (steam rating, star rating, vote count, tags)
   - Update your custom columns with the downloaded values

> **Note:** Occasionally a browser window may open if the JSON API and lightweight HTTP both fail for a book - just ignore it and let the plugin work. Don't close the window or click anything on the page.

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
2. Fetches the book's Romance.io detail page - first trying the JSON API, then a lightweight HTTP request, then via Chrome as a final fallback if needed
3. Parses the response to extract steam rating, star rating, rating count, and tags
4. Filters and formats tags based on your settings
5. Updates your custom columns with the downloaded data

## Tag Filtering

Tags are ordered by vote count (most popular first) and limited by the **Max Tags** setting. If a book has 15 tags and **Max Tags** is set to 10, the plugin will only download the 10 highest-voted tags for that book.

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
calibre-debug test_http_fields_parsing.py
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
- The plugin tries the JSON API first, then a lightweight HTTP fetch, and only uses Chrome as a final fallback
- Without Chrome, most books still download fine via the JSON API or lightweight HTTP fetch
- Install Chrome from [google.com/chrome](https://www.google.com/chrome/) if you see this warning or downloads are failing
- **Linux with Chrome installed as a flatpak:** the plugin can find Chrome automatically, but if Calibre is also a flatpak you need to run this once in a terminal and restart Calibre:
  ```
  flatpak override --user --filesystem=/var/lib/flatpak:ro com.calibre_ebook.calibre
  ```

**Slow performance:**
- Most books download in seconds via the JSON API or a lightweight HTTP fetch. Chrome (via browser automation) is only used as a last resort when those methods fail, and takes 10-30 seconds per book

## Support

Report issues on [GitHub Issues](https://github.com/plain-cover/calibre_plugins/issues). Include:
- Exact **title and author in Calibre**, and the **expected Romance.io URL**
- **Which plugin** - if the issue happened when clicking the magnifying glass icon, then it is due to the **Romance.io Fields** plugin; if it happened during a metadata download, it is the **Romance.io** plugin
- **Calibre version** - shown in the bottom-left of the Calibre window, or via **Help > About Calibre**
- **Plugin version** - **Preferences > Plugins**, find the plugin (Romance.io Fields), note the version (e.g. 1.0.0)
- **Error logs** - click the **Jobs: 0** button in the bottom-right corner of Calibre after the job runs. Select the most recent job — there may be two: **Finding books on Romance.io** (the search step) and **Download Romance.io Fields** (the download step). Choose whichever failed (usually the latest one), click **Show job details**, and copy the output.

For more verbose logs, right-click the **Preferences** button (gear icon) and choose **Restart in debug mode**.
