# Romance.io Fields - Custom Columns Plugin for Calibre

> **For user-facing install and usage instructions, see the [main README](../README.md).**

A Calibre interface action plugin that fetches Romance.io-specific data (steam rating, star rating, vote count, tags), writes it into user-configured custom columns, and can add ratings to Calibre's standard Tags field for display on an e-reader.

## What This Plugin Does

1. Searches [Romance.io](https://www.romance.io/) for books matching the title and author and, if found, stores the book's Romance.io ID
2. Loads each book's Romance.io data to extract steam rating, star rating, vote count, and community tags
3. Preserves the existing combined tag output and, when configured, copies Romance.io general tags, content warnings, geography, and format tags into separate columns
4. Filters the combined tags by the maximum count setting; categorized columns receive their complete matching groups
5. Writes values into the user-configured custom columns and optionally adds steam and star ratings to Calibre's standard Tags field
6. Optionally prompts before saving

## Configuration

**Preferences > Plugins > Romance.io Fields > Customize plugin**

| Setting | Default | Description |
|---|---|---|
| Refresh existing fields | ✓ checked | Re-download all fields even if already set (ID is never overwritten) |
| Prompt to save | ☐ unchecked | Show confirmation dialog before writing to library |
| Get tags directly from website (slower but includes additional community tags) | ☐ unchecked | Try the browser first to get the full JS-rendered tag set including community-voted tags; falls back to the normal JSON → lightweight HTTP → Chrome path if the browser is unavailable |
| Add steam rating to Calibre Tags | ☐ unchecked | Add a tag like `Romance.io steam: 3` |
| Add star rating to Calibre Tags | ☐ unchecked | Add a tag like `Romance.io stars: 4.3` |
| Steam column | - | Lookup name of your steam rating column |
| All tags column (combined) | - | Optional destination for the original combined, unprefixed tag list |
| Maximum combined tags | 50 | Cap on the combined tag list; categorized columns receive their complete matching groups |
| General tags column | - | Optional additional copy containing ordinary tags only (e.g. magic) |
| Content warnings column | - | Optional additional copy containing content warnings only (e.g. gambling) |
| Geography column | - | Optional additional copy containing geography tags only (e.g. england) |
| Format tags column | - | Optional additional copy containing format tags only (e.g. dual pov) |
| Star rating column | - | Lookup name of your star rating column |
| Rating count column | - | Lookup name of your vote count column |

## Custom Columns Setup

The plugin writes data from [Romance.io](https://romance.io) into custom columns in Calibre. You need to create the columns yourself first so we have a place to put the data. Each value you want to store (Romance.io ID, steam rating, star rating, vote count, or tags) needs its own column with the right column type so Calibre knows how to store and sort the data. Optionally, you can configure tag category columns, which do not replace or modify the combined tags column. If you only want steam and/or star ratings added to Calibre's standard Tags field, those ratings do not require custom columns.

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

Romance.io Tags (combined):

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Tags column](../images/Add%20custom%20column%20-%20tags.png)

The four category columns are optional. Create columns for any or all of the categories you want to use:

Romance.io General Tags:

![Calibre "Create a custom column" dialog for an optional General Tags column using the lookup name #romiogeneraltags](../images/Add%20custom%20column%20-%20general%20tags.png)

Romance.io Content Warnings:

![Calibre "Create a custom column" dialog for an optional Content Warnings column using the lookup name #romiocontent](../images/Add%20custom%20column%20-%20content%20warnings.png)

Romance.io Format Tags:

![Calibre "Create a custom column" dialog for an optional Format Tags column using the lookup name #romioformat](../images/Add%20custom%20column%20-%20format%20tags.png)

Romance.io Geography Tags:

![Calibre "Create a custom column" dialog for an optional Geography Tags column using the lookup name #romiogeography](../images/Add%20custom%20column%20-%20geography%20tags.png)

Once created, the selected columns appear in Calibre's custom-column preferences alongside the existing Romance.io fields:

![Calibre Add your own columns preferences showing Romance.io ID, ratings, combined tags, and the four optional tag category columns](../images/Calibre%20preferences%20-%20custom%20columns.png)

Here's a reference table for creating each column. Lookup names can be anything you choose - you'll map them to your chosen names in Step 2.

| Field | Lookup Name | Column Type | Additional Setup | Description |
|-------|-------------|-------------|------------------|-------------|
| Romance.io ID | `#romanceio` | Column built from other columns | Template `{identifiers:select(romanceio)}` and sort by `Text` | ID used in Romance.io URL. Show this column as an indicator of whether the book was able to be found on Romance.io. |
| Romance.io Steam Rating | `#romiosteam` | Integers | | Values 1-5 based on [Romance.io steam ratings](https://www.romance.io/steamrating) |
| Romance.io Stars | `#romiostars` | Floating point numbers | With 2 decimals | Star rating from Romance.io user votes |
| Romance.io Vote Count | `#romiovotes` | Integers | | Total number of star ratings for a book on Romance.io |
| Romance.io Tags (combined) | `#romiotags` | Comma-separated text, like tags | | All user-sourced tags from the Romance.io book detail page |
| Romance.io General Tags | `#romiogeneraltags` | Comma-separated text, like tags | | Ordinary tropes, themes, genres, and character/story tags copied into their own column |
| Romance.io Content Warnings | `#romiocontent` | Comma-separated text, like tags | | Content-warning tags copied into their own column |
| Romance.io Geography | `#romiogeography` | Comma-separated text, like tags | | Countries, regions, and other geography tags copied into their own column |
| Romance.io Format Tags | `#romioformat` | Comma-separated text, like tags | | Romance.io's format tags, such as audiobook, point of view, length, and series structure copied into their own column |

You can configure the combined column, any category columns, or both. Adding tag category columns will not affect what tags appear in the combined column.

**Step 2 - Map columns in plugin settings**

Click the dropdown arrow next to the Romance.io icon and select **Customize plugin**:

![Screenshot of the main toolbar in Calibre with the Romance.io Fields plugin dropdown selected](../images/Main%20toolbar%20icon.png)

You can also open **Preferences > Plugins**, find "Romance.io Fields", and click **Customize plugin**.

In the customization menu, map each field to the lookup name of the column you created:

![Calibre "Customize Romance.io Fields" dialog mapping the combined tags, four optional tag category columns, and rating fields to custom columns](../images/Customize%20plugin%20field%20mappings.png)

Leave any field blank if you do not want the plugin to populate that column.

Additional customization settings:
- **Refresh existing fields when downloading from Romance.io** - When checked (default), all configured fields are updated with the latest data from Romance.io, even if they already have values. The Romance.io ID is never overwritten to avoid unnecessary searches. To change or re-download the ID, manually delete it from the book's identifiers. Uncheck if you have manually edited field values and don't want them overwritten.
- **Prompt to save fields after downloading** - At the end of the download process, user can confirm if they would like to add the downloaded metadata for all selected books
- **Get tags directly from website (slower but includes additional community tags)** - When checked, the plugin tries to open the Romance.io page in a Chrome browser first. This gives you the full community-voted tag set that is only available after JavaScript renders the page. If the browser is unavailable or fails, the plugin resumes the normal JSON → lightweight HTTP → Chrome fallback path. Unchecked (default): the plugin starts with JSON, which is faster and works without Chrome for most users.
- **Add steam rating to Calibre Tags** - Adds a tag like `Romance.io steam: 3` to Calibre's standard Tags field. This works without a steam-rating custom column. Existing tags are preserved, and re-running the plugin replaces only its own previous steam tag.
- **Add star rating to Calibre Tags** - Adds a tag like `Romance.io stars: 4.3` to Calibre's standard Tags field. This works without a star-rating custom column. Existing tags are preserved, and re-running the plugin replaces only its own previous star tag.
- **Maximum combined tags to download** - Maximum number written to the combined tags column (default: 50); categorized columns remain complete
- **Categorized tag columns** - Optional additional destinations for general tags, content warnings, geography, and format tags. JSON tags are categorized with a taxonomy bundled with the plugin, so these columns do not add a webpage request or require Chrome. The groups do not change the combined tags column and are not truncated by the combined maximum-tags setting. Format tags will contain detailed length and series tags that the combined column omits.
  > **Why do my tags look different from what I see on Romance.io?**
  > Romance.io displays two layers of tags: a core set (tropes, genres, etc.) stored in their database and returned by the API, and additional community-voted tags injected into the page by JavaScript after it loads. The default fast fetch (JSON API / lightweight HTTP) retrieves only the core set. To get the community tags too, enable this option - but be aware it requires Chrome and is slower since a browser window will have to open for each book.

## Usage

### Download Fields

1. Select one or more books in your library
2. Click the Romance.io plugin button
3. The plugin will:
   - Check if the book is already associated with a Romance.io identifier
   - If not found, search Romance.io by title/author
   - Download the selected fields (steam rating, star rating, vote count, combined tags, and any configured category groups)
   - Update your custom columns and configured rating tags with the downloaded values

With the optional category columns configured, the original combined tags remain available while general tags, content warnings, geography, and format details are also shown separately. This makes it easier to display, sort, or filter by one kind of tag without losing the complete tag list:

![Populated Calibre library columns showing combined Romance.io Tags alongside separate General Tags, Content Warnings, Format Tags, and Geography Tags](../images/Calibre%20optional%20tag%20category%20columns.png)

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
5. Updates your custom columns and configured rating tags with the downloaded data

## Tag Limiting

The **Maximum combined tags** setting keeps the first tags in the order Romance.io returns them. The plugin does not receive or sort by per-tag vote counts. If a book has 15 combined tags and the maximum is 10, it keeps the first 10. Optional category columns remain complete.

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
calibre-debug -e test_rating_tags.py        # Rating tag formatting and safe replacement
calibre-debug test_json_search_matching.py  # Best-match selection from JSON search results
calibre-debug test_tag_mapping.py           # Display-name consistency, topics-page HTML extraction
calibre-debug test_tag_slug_conversion.py   # Slug-to-display-name conversion (copied from common/)
calibre-debug test_html_sanitizer.py        # sanitize_html_for_lxml() strips XML 1.0 illegal chars (copied from common/)
calibre-debug test_field_building.py        # Duplicate-column detection and complete category-field output
python ../common/check_romanceio_tag_taxonomy.py --book-html-file test_data/funny_story_source.html --topics-html-file test_data/romanceio_topics_page.html
```

The separate **Romance.io Tag Updates (Weekly Maintenance Check)** GitHub Actions workflow performs a browser-free live check each week. It validates both slug-to-display-name mappings and the content-warning, geography, and format categories. When Romance.io changes its taxonomy, the failed job is explicitly labeled **Romance.io tag taxonomy changed** and explains that this is a routine maintenance alert rather than a broken test pipeline. Refresh both bundled maps with `python common/update_tag_mappings.py` from the workspace root, review the generated changes, and commit them.

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

## Tag Limiting Detail

The plugin preserves the order supplied by Romance.io and takes the first `max_tags` values for the combined column. It does not receive per-tag vote counts, apply a minimum-vote filter, or sort tags itself. Optional category columns are not capped by this setting.

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
- Categorized JSON tags use the bundled taxonomy and do not require Chrome or an extra HTTP request
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
- **Error logs** - click the **Jobs: 0** button in the bottom-right corner of Calibre after the job runs. Select the most recent job - there may be two: **Finding books on Romance.io** (the search step) and **Download Romance.io Fields** (the download step). Choose whichever failed (usually the latest one), click **Show job details**, and copy the output.

For more verbose logs, right-click the **Preferences** button (gear icon) and choose **Restart in debug mode**.
