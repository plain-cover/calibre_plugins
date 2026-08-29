# Calibre Plugins for Romance.io

Two Calibre plugins that link your library with [Romance.io](https://romance.io), a website for romance novels that provides steam ratings, user star ratings, and detailed tagging (tropes, themes, settings, etc.) that you can't get from Goodreads or Amazon.

- Adds a clickable link to the book's Romance.io page in Calibre's book details panel (both plugins)
- Adds cover art, series, star rating, description, and publication date from Romance.io (Romance.io metadata plugin)
- Adds Romance.io tags to Calibre's Tags field based on a customizable mapping (Romance.io metadata plugin)
- Adds steam rating, star rating, and vote count to custom columns, with optional steam/star tags for e-readers (Romance.io Fields plugin)
- Adds Romance.io tags to a custom column so you can sort and filter your library by tropes, themes, settings, and more (Romance.io Fields plugin)
- Optionally copies Romance.io general tags, content warnings, geography, and format tags into separate custom columns without changing the combined tags column (Romance.io Fields plugin)

![Screenshot of Calibre showing each feature of the Romance.io plugins emphasized with red boxes and arrows](images/Full%20Calibre.png)

> **Two types of plugin:** The **Romance.io** plugin is a *metadata source plugin* - it plugs into Calibre's built-in metadata download system, the same place as other sources like Amazon or Goodreads. The **Romance.io Fields** plugin is an *interface action plugin* - it adds a toolbar button that you click manually to fetch data into custom columns you create. They work well together: running the Romance.io metadata download first stores an ID on the book, and Romance.io Fields uses that stored ID to skip re-searching and go straight to downloading fields.

**[Installation Instructions](#installation)**

## Romance.io - Metadata Source Plugin for Calibre

Adds [Romance.io](https://romance.io) as an additional source for Calibre's metadata download system. When you run a metadata download on a book, Calibre searches for the book by title and author on sites including [Romance.io](https://romance.io), and if the book is found, connects the book in your library to the book on [Romance.io](https://romance.io) so that you can click a link to go straight to the book's [Romance.io](https://romance.io) page, and see metadata like the cover image, series, star rating, description, date published, and genre tags in your Calibre library.

![Calibre "Downloading metadata" menu, first page, showing a book result that is linked to a result from Romance.io (Funny Story by Emily Henry)](images/Metadata%20download%20result1.png)

![Calibre "Downloading metadata" menu, second page, showing an option to download a book cover from Romance.io (Funny Story by Emily Henry)](images/Metadata%20download%20result2.png)

![Screenshot of the Calibre book details panel with an arrow pointing to the link to Romance.io](images/Link%20to%20Romanceio.png)

Completing the metadata download will populate fields from [Romance.io](https://romance.io): series, series number, tags, star rating, description (stored as Comments in Calibre), date published, and ID used in the [Romance.io](https://romance.io) URL.

![Screenshot of the Calibre "Edit metadata" panel before searching Romance.io for metadata](images/Scythe%20before.png) ![Screenshot of the Calibre "Edit metadata" panel after searching Romance.io for metadata](images/Scythe%20after.png)

### Downloading metadata

1. Once the plugin is loaded, ensure that it is enabled by going to Preferences > Metadata download and checking the box next to "Romance.io".
2. Select a book, click **Edit metadata** in the main Calibre toolbar, then click **Download metadata**, and wait for results. If there is a match found for the book on Romance.io, Calibre will show "**See at:** Romance.io" on the right panel for the matching search result. Click "OK" to match the book to this Romance.io ID and download metadata from [Romance.io](https://romance.io).

    ![Calibre "Downloading metadata" menu, first page, showing a book result that is linked to a result from Romance.io (Funny Story by Emily Henry)](images/Metadata%20download%20result1.png)

### Configuration

#### Metadata fields to download
You can choose which fields you want to populate from [Romance.io](https://romance.io). There are two places in Calibre where fields can be turned on or off - if a field isn't downloading, check both:

1. **Global field list** (**Preferences > Metadata download**, main page): Calibre has a global list of fields it will accept from any source. If a field is unchecked here, it won't be downloaded even if the source provides it.

    ![Screenshot of the Preferences > Metadata download page showing the global field checkboxes](images/Metadata%20download%20-%20global%20fields.png)

2. **Per-source field list**: from the global Configure Metadata menu pictured above, if you select the Romance.io plugin from the list on the left, then click **Configure selected source**, here you can check or uncheck individual fields to control which fields the plugin downloads.

     ![Screenshot of the Configure selected source dialog showing the Metadata fields to download checkboxes](images/Configure%20Metadata%20download%20-%20fields.png)

#### Tag Mappings

**Preferences > Metadata download > Romance.io > Configure selected source**

**Romance.io tag to Calibre tag mappings** - controls how Romance.io tags are imported into Calibre's Tags field. Use the green "+" and red "-" buttons to add or remove mappings. Create one row for each Romance.io tag you want to map to one or more Calibre tags. The text you enter for the Romance.io tag must match how the tag looks on the website exactly. Any Romance.io tags that are not mapped will be ignored.

  ![Screenshot of the Configure Metadata download dialog with the "Filter and map Romance.io tags to Calibre tags" checkbox checked](images/Configure%20Metadata%20download.png)

  To get all Romance.io tags as individual Calibre tags, uncheck **"Filter and map Romance.io tags to Calibre tags"**:

  ![Configure Metadata download dialog showing the "Filter and map Romance.io tags to Calibre tags" checkbox unchecked](images/Uncheck%20map%20tags.png)

  - **Checked (default):** Only tags listed in the mapping table are imported. Each Romance.io tag maps to one or more Calibre tags of your choosing. Tags not in the table are dropped.
  - **Unchecked:** All Romance.io tags are imported as individual Calibre tags, with no filtering or renaming. Use this if you want to import every Romance.io tag for each book.

  With the box unchecked, the metadata download will import all tags from Romance.io as Calibre tags:

  ![Metadata download result showing all Romance.io tags as individual Calibre tags](images/Uncheck%20map%20tags%20result.png)

## Romance.io Fields - Custom Columns Plugin for Calibre

A toolbar button that fetches steam rating, star rating, vote count, and community tags from [Romance.io](https://romance.io) and writes them into custom columns in your library. Tags can remain in one combined column and can also be copied into separate columns for general tags, content warnings, geography, and format tags. It can also add steam and star ratings to Calibre's standard Tags field for display on an e-reader. Once set up, you can sort and filter your entire library by any of these fields.

![Screenshot of Calibre showing each feature of the Romance.io plugins emphasized with red boxes and arrows](images/Full%20Calibre.png)

### Setup

**Step 1 - Create custom columns**

The plugin writes data from [Romance.io](https://romance.io) into custom columns in Calibre. You need to create the columns yourself first so we have a place to put the data. Each value you want to store (Romance.io ID, steam rating, star rating, vote count, or tags) needs its own column with the right column type so Calibre knows how to store and sort the data. If you only want steam and/or star ratings added to Calibre's standard Tags field, those ratings do not require custom columns.

Go to **Preferences > Add your own columns** and add a new column for each field you want. You don't have to create all of them - only the columns you want to be able to sort and filter on. Here's what each column should look like when you're creating it:

Romance.io ID:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io ID column](images/Add%20custom%20column%20-%20ID.png)

Romance.io Steam Rating:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Steam Rating column](images/Add%20custom%20column%20-%20steam.png)

Romance.io Stars:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Stars column](images/Add%20custom%20column%20-%20stars.png)

Romance.io Vote Count:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Vote Count column](images/Add%20custom%20column%20-%20votes.png)

Romance.io Tags (combined):

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Tags column](images/Add%20custom%20column%20-%20tags.png)

The four category columns are optional. Create custom columns only for the categories you want to have a separate column for:

Romance.io General Tags:

![Calibre "Create a custom column" dialog for an optional General Tags column using the lookup name #romiogeneraltags](images/Add%20custom%20column%20-%20general%20tags.png)

Romance.io Content Warnings:

![Calibre "Create a custom column" dialog for an optional Content Warnings column using the lookup name #romiocontent](images/Add%20custom%20column%20-%20content%20warnings.png)

Romance.io Format Tags:

![Calibre "Create a custom column" dialog for an optional Format Tags column using the lookup name #romioformat](images/Add%20custom%20column%20-%20format%20tags.png)

Romance.io Geography Tags:

![Calibre "Create a custom column" dialog for an optional Geography Tags column using the lookup name #romiogeography](images/Add%20custom%20column%20-%20geography%20tags.png)

Once you've created all the columns you want, they'll appear in your preferences like this:

![Calibre Add your own columns preferences showing Romance.io ID, ratings, combined tags, and the four optional tag category columns](images/Calibre%20preferences%20-%20custom%20columns.png)

Here's a table you can use for a reference when creating each column. The lookup names can be anything you choose (examples are provided below), since you'll map them to whatever you chose as a name in the next step.

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

![Screenshot of the main toolbar in Calibre with the Romance.io Fields plugin dropdown selected](images/Main%20toolbar%20icon.png)

You can also open **Preferences > Plugins**, find "Romance.io Fields", and click **Customize plugin**.

In the customization menu, map each field to the lookup name of the column you created:

![Calibre "Customize Romance.io Fields" dialog mapping the combined tags, four optional tag category columns, and rating fields to custom columns](images/Customize%20plugin%20field%20mappings.png)

Leave any field blank if you do not want the plugin to populate that column.

### Downloading fields

Select one or more books and click the Romance.io toolbar button. The plugin searches [Romance.io](https://romance.io) for the title and author, then fetches fields (e.g. ratings and tags) for the matching book. After clicking the button, if a matching book is found on [Romance.io](https://romance.io), the data will appear in your custom columns as soon as the lookup job finishes.

![Screenshot of the main toolbar in Calibre with the Romance.io Fields plugin dropdown selected](images/Click%20toolbar%20button.png)

With the optional category columns configured, the original combined tags remain available while general tags, content warnings, format details, and geography are also shown separately. This makes it easier to display, sort, or filter by one kind of tag without losing the complete tag list:

![Populated Calibre library columns showing combined Romance.io Tags alongside separate General Tags, Content Warnings, Format Tags, and Geography Tags](images/Calibre%20optional%20tag%20category%20columns.png)

**To refresh data for books you've already downloaded:** select the books you want to refresh and click the Romance.io toolbar button again. If the Romance.io ID is already stored, it skips the search and goes straight to re-fetching the data, which is faster.

### Configuration

You can configure the plugin from the **dropdown arrow next to the plugin's icon > Customize plugin**, or **Preferences > Plugins > Romance.io Fields > Customize plugin**.

Under **Romance.io tag options**, **All tags column (combined)** retains the original unprefixed tag list. The four categorized destinations are independent and optional. If both combined and categorized columns are selected, the plugin writes both. The maximum-tags setting continues to limit the combined column; categorized columns receive the complete matching group, including categorized length or series tags that the historical combined output omits.

Under **Rating tag options**, enable **Add steam rating to Calibre Tags** and/or **Add star rating to Calibre Tags** to create tags such as `Romance.io steam: 3` and `Romance.io stars: 4.3`. These options do not require custom columns. Existing tags are preserved, and re-running the plugin replaces only older rating tags created by the plugin.

## Installation

The two plugins are independent - install one or both depending on which features you want.

In Calibre, go to **Preferences > Plugins > Get new plugins**, search for "Romance.io", select the plugin(s) you want, and click **Install**. Restart Calibre when prompted.

For the Romance.io Fields plugin, you may have an extra step to ensure the plugin icon appears on the main toolbar. If you see a window asking you to "Select the toolbars and/or menus" to add the plugin to, select "The main toolbar" and "The main toolbar when a device is connected." If you don't see this prompt, you may need to add the plugin to the main toolbar manually in **Preferences > Toolbars & menus** and select "The main toolbar" from the dropdown, then find "Romance.io" in the available actions and click the ">" button to add it to the toolbar.

**To get the latest version** before it's published to the plugin store, download the zip from the [GitHub releases page](https://github.com/plain-cover/calibre_plugins/releases) and install via **Preferences > Plugins > Load plugin from file**.
- `Romance.io.zip` - metadata source plugin (ID, cover, series, rating, description, tags, date published)
- `Romance.io Fields.zip` - custom columns plugin (steam, stars, vote count, combined tags, and optional categorized tags)

## Notes

**You can process one book or many at once.** Select any number of books and click the Romance.io plugin button in the main Calibre toolbar to download in bulk. The download will run in the background and alert you when it's done. You can track the job's progress in the bottom-right corner of the Calibre window.

**A browser window may open during downloads.** The plugin uses the JSON API for searches. For book details it tries a lightweight webpage request first, then Chrome, and keeps the legacy JSON book-details route as a final fallback. Categorized JSON tags use a taxonomy bundled with the plugin, so configuring category columns does not add a webpage request or require Chrome. Browser-based lookups can take ~5-30 seconds per book.

**Chrome is required only for the browser-based metadata fallback and the full community-voted tag set.** Without Chrome, the plugin can still use the JSON API and lightweight webpage requests. Install Chrome from [google.com/chrome](https://www.google.com/chrome/) if you want the final fallback or full community tags. Chrome doesn't need to be your default browser, it just needs to be installed. On Apple Silicon Macs (M1/M2/M3/M4), Chrome's browser automation also requires Rosetta 2 - if that's missing, the plugin's job log will tell you how to install it.

**Linux with Chrome installed as a flatpak:** the plugin can find and use a flatpak-installed Chrome automatically. If Calibre is also a flatpak, you need to run this once in a terminal and restart Calibre:
```
flatpak override --user --filesystem=/var/lib/flatpak:ro com.calibre_ebook.calibre
```

**Wrong book matched, or your title/author in Calibre intentionally differs from Romance.io?** The automatic search matches by title and author - if your library uses a different edition name, spelling, or you've renamed the book, the search may fail or pick the wrong result. That's fine: you can still manually link any book to its Romance.io page. Find the book on [Romance.io](https://romance.io) and open its **book detail page** (not the series page - the URL should contain `/books/`), then copy the ID from the URL (e.g. `5484ecd47a5936fb0405756c` from `romance.io/books/5484ecd47a5936fb0405756c/...`). In Calibre, open **Edit metadata** for the book, go to the **Ids** field, and add `romanceio:5484ecd47a5936fb0405756c`. After saving, the link to Romance.io will work in the book details panel, and Romance.io Fields will be able to download data for the book.

**Tags are not downloaded in any particular order.** Calibre automatically alphabetizes tags in the tag browser, so the download order doesn't matter.

**Only English is supported for now.** If you're interested in support for another language, let me know by opening a [GitHub Issue](https://github.com/plain-cover/calibre_plugins/issues).

## Issues

[GitHub Issues](https://github.com/plain-cover/calibre_plugins/issues). Please include as much detail as possible:

- **Title and author** as they appear in Calibre, and the **expected Romance.io URL**
- **Calibre version** - shown in the bottom-left of the Calibre window, or via **Help > About Calibre**
- **Plugin version** - go to **Preferences > Plugins**, find the plugin, and note the version number shown
- **Error logs or tracebacks**:
  - **Romance.io plugin** (metadata download): after the download ends, click the **View log** button and copy the contents.
  - **Romance.io Fields plugin** (toolbar button): click the **Jobs: 0** button in the bottom-right corner of Calibre after the job finishes running. There may be two jobs - **Finding books on Romance.io** (search) and **Download Romance.io Fields** (download). Select whichever failed (usually the latest one), click **Show job details**, and copy the output.

**For more verbose logs**, start Calibre in debug mode: right-click the **Preferences** button (gear icon in the toolbar) and choose **Restart in debug mode**. Log output will be printed to the terminal that opens.

## For developers

### Build and run

```bash
cd romanceio && ./build.sh
cd ../romanceio_fields && ./build.sh
calibre-debug -g
```

`build.sh` vendors dependencies and copies shared code from `common/` before zipping the plugin. Run it for both plugins before launching. See [romanceio/README.md](romanceio/README.md) and [romanceio_fields/README.md](romanceio_fields/README.md) for per-plugin build details and test commands.

The **Romance.io Tag Updates (Weekly Maintenance Check)** GitHub Actions workflow compares the bundled display-name and category mappings with Romance.io's live taxonomy using plain HTTP. A failure labeled **Romance.io tag taxonomy changed** means the site data changed and the mappings need a routine refresh with `python common/update_tag_mappings.py`; it does not mean the general test pipeline broke.

### Why are dependencies bundled in the zip?

Calibre runs plugins in its own embedded Python environment - you can't install packages at runtime with pip. So all dependencies (seleniumbase, lxml, requests, etc.) are installed into the plugin folder at build time and bundled into the zip. See [common/README.md](common/README.md) for details on the shared code layer.

