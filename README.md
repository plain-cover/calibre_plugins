# Calibre Plugins for Romance.io

Two Calibre plugins that link your library with [Romance.io](https://romance.io), a website for romance novels that provides steam ratings, user star ratings, and detailed tagging (tropes, themes, settings, etc.) that you can't get from Goodreads or Amazon.

- Adds a clickable link to the book's Romance.io page in Calibre's book details panel (both plugins)
- Adds cover art, series, and publication date from Romance.io (Romance.io metadata plugin)
- Adds Romance.io tags to Calibre's Tags field based on a customizable mapping (Romance.io metadata plugin)
- Adds steam rating, star rating, and vote count to custom columns (Romance.io Fields plugin)
- Adds Romance.io tags to a custom column so you can sort and filter your library by tropes, themes, settings, and more (Romance.io Fields plugin)

![Screenshot of Calibre showing each feature of the Romance.io plugins emphasized with red boxes and arrows](images/Full%20Calibre.png)

> **Two types of plugin:** The **Romance.io** plugin is a *metadata source plugin* - it plugs into Calibre's built-in metadata download system, the same place as other sources like Amazon or Goodreads. The **Romance.io Fields** plugin is an *interface action plugin* - it adds a toolbar button that you click manually to fetch data into custom columns you create. They work well together: running the Romance.io metadata download first stores an ID on the book, and Romance.io Fields uses that stored ID to skip re-searching and go straight to downloading fields.

**[Installation Instructions](#installation)**

## Romance.io - Metadata Source Plugin for Calibre

Adds [Romance.io](https://romance.io) as an additional source for Calibre's metadata download system. When you run a metadata download on a book, Calibre searches for the book by title and author on sites including [Romance.io](https://romance.io), and if the book is found, connects the book in your library to the book on [Romance.io](https://romance.io) so that you can click a link to go straight to the book's [Romance.io](https://romance.io) page, and see metadata like the cover image, series, date published, and genre tags in your Calibre library.

![Calibre "Downloading metadata" menu, first page, showing a book result that is linked to a result from Romance.io (Funny Story by Emily Henry)](images/Metadata%20download%20result1.png)

![Calibre "Downloading metadata" menu, second page, showing an option to download a book cover from Romance.io (Funny Story by Emily Henry)](images/Metadata%20download%20result2.png)

![Screenshot of the Calibre book details panel with an arrow pointing to the link to Romance.io](images/Link%20to%20Romanceio.png)

Completing the metadata download will populate fields from [Romance.io](https://romance.io): series, series number, tags, date published, and ID used in the [Romance.io](https://romance.io) URL.

![Screenshot of the Calibre "Edit metadata" panel before searching Romance.io for metadata](images/Scythe%20before.png) ![Screenshot of the Calibre "Edit metadata" panel after searching Romance.io for metadata](images/Scythe%20after.png)

### Downloading metadata

1. Once the plugin is loaded, ensure that it is enabled by going to Preferences > Metadata download and checking the box next to "Romance.io".
2. Select a book, click **Edit metadata** in the main Calibre toolbar, then click **Download metadata**, and wait for results. If there is a match found for the book on Romance.io, Calibre will show "**See at:** Romance.io" on the right panel for the matching search result. Click "OK" to match the book to this Romance.io ID and download metadata from [Romance.io](https://romance.io).

![Calibre "Downloading metadata" menu, first page, showing a book result that is linked to a result from Romance.io (Funny Story by Emily Henry)](images/Metadata%20download%20result1.png)

### Configuration

**Preferences > Metadata download > Romance.io > Configure selected source**

- **Metadata fields to download** - choose which fields you want to populate from [Romance.io](https://romance.io)
- **Romance.io tag to Calibre tag mappings** - controls how Romance.io tags are imported into Calibre's Tags field. Use the green "+" and red "-" buttons to add or remove mappings. Create one row for each Romance.io tag you want to map to one or more Calibre tags. The text you enter for the Romance.io tag must match how the tag looks on the website exactly. Any Romance.io tags that are not mapped will be ignored.

  ![Screenshot of the Configure Metadata download dialog with the "Filter and map Romance.io tags to calibre tags" checkbox checked](images/Configure%20Metadata%20download.png)

  To get all Romance.io tags as individual Calibre tags, uncheck **"Filter and map Romance.io tags to Calibre tags"**:

  - **Checked (default):** Only tags listed in the mapping table are imported. Each Romance.io tag maps to one or more Calibre tags of your choosing. Tags not in the table are dropped.
  - **Unchecked:** All Romance.io tags are imported as individual Calibre tags, with no filtering or renaming. Use this if you want to import every Romance.io tag for each book.

  ![Configure Metadata download dialog showing the "Filter and map Romance.io tags to Calibre tags" checkbox unchecked](images/Uncheck%20map%20tags.png)

  With the box unchecked, the metadata download will import all tags from Romance.io as Calibre tags:

  ![Metadata download result showing all Romance.io tags as individual Calibre tags](images/Uncheck%20map%20tags%20result.png)

## Romance.io Fields - Custom Columns Plugin for Calibre

A toolbar button that fetches steam rating, star rating, vote count, and community tags from [Romance.io](https://romance.io) and writes them into custom columns in your library. Once set up, you can sort and filter your entire library by any of these fields.

![Screenshot of Calibre showing each feature of the Romance.io plugins emphasized with red boxes and arrows](images/Full%20Calibre.png)

### Setup

**Step 1 - Create custom columns**

The plugin writes data from [Romance.io](https://romance.io) into custom columns in Calibre. You need to create the columns yourself first so we have a place to put the data. Each field (Romance.io ID, steam rating, star rating, vote count, tags) needs its own column with the right column type so Calibre knows how to store and sort the data.

Go to **Preferences > Add your own columns** and add a new column for each field you want. You don't have to create all of them - only the columns you want to be able to sort and filter on. Here's what each column should look like when you're creating it:

Romance.io ID:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io ID column](images/Add%20custom%20column%20-%20ID.png)

Romance.io Steam Rating:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Steam Rating column](images/Add%20custom%20column%20-%20steam.png)

Romance.io Stars:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Stars column](images/Add%20custom%20column%20-%20stars.png)

Romance.io Vote Count:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Vote Count column](images/Add%20custom%20column%20-%20votes.png)

Romance.io Tags:

![Calibre "Create a custom column" menu showing the configuration details for the Romance.io Tags column](images/Add%20custom%20column%20-%20tags.png)

Once you've created all the columns you want, they'll appear in your preferences like this:

![Calibre preferences menu showing the configuration details for five custom columns: Romance.io ID, Steam, Romance.io Tags, Romance.io Stars, and Romance.io Vote Count](images/Calibre%20preferences%20-%20custom%20columns.png)

Here's a table you can use for a reference when creating each column. The lookup names can be anything you choose (examples are provided below), since you'll map them to whatever you chose as a name in the next step.

| Field | Lookup Name | Column Type | Additional Setup | Description |
|-------|-------------|-------------|------------------|-------------|
| Romance.io ID | `#romanceio` | Column built from other columns | Template `{identifiers:select(romanceio)}` and sort by `Text` | ID used in Romance.io URL. Show this column as an indicator of whether the book was able to be found on Romance.io. |
| Romance.io Steam Rating | `#romiosteam` | Integers | | Values 1-5 based on [Romance.io steam ratings](https://www.romance.io/steamrating) |
| Romance.io Stars | `#romiostars` | Floating point numbers | With 2 decimals | Star rating from Romance.io user votes |
| Romance.io Vote Count | `#romiovotes` | Integers | | Total number of star ratings for a book on Romance.io |
| Romance.io Tags | `#romiotags` | Comma-separated text, like tags | | User-sourced tags from Romance.io |

**Step 2 - Map columns in plugin settings**

Click the dropdown arrow next to the Romance.io icon and select **Customize plugin**:

![Screenshot of the main toolbar in Calibre with the Romance.io Fields plugin dropdown selected](images/Main%20toolbar%20icon.png)

You can also open **Preferences > Plugins**, find "Romance.io Fields", and click **Customize plugin**.

In the customization menu, map each field to the lookup name of the column you created:

![Calibre "Customize Romance.io Fields" menu showing the mapping of fields to column lookup names](images/Customize%20plugin%20field%20mappings.png)

### Downloading fields

Select one or more books and click the Romance.io toolbar button. The plugin searches [Romance.io](https://romance.io) for the title and author, then fetches fields (e.g. ratings and tags) for the matching book. After clicking the button, if a matching book is found on [Romance.io](https://romance.io), the data will appear in your custom columns as soon as the lookup job finishes.

![Screenshot of the main toolbar in Calibre with the Romance.io Fields plugin dropdown selected](images/Click%20toolbar%20button.png)

**To refresh data for books you've already downloaded:** select the books you want to refresh and click the Romance.io toolbar button again. If the Romance.io ID is already stored, it skips the search and goes straight to re-fetching the data, which is faster.

### Configuration

You can configure the plugin from the **dropdown arrow next to the plugin's icon > Customize plugin**, or **Preferences > Plugins > Romance.io Fields > Customize plugin**.

## Installation

The two plugins are independent - install one or both depending on which features you want.

In Calibre, go to **Preferences > Plugins > Get new plugins**, search for "Romance.io", select the plugin(s) you want, and click **Install**. Restart Calibre when prompted.

For the Romance.io Fields plugin, you may have an extra step to ensure the plugin icon appears on the main toolbar. If you see a window asking you to "Select the toolbars and/or menus" to add the plugin to, select "The main toolbar" and "The main toolbar when a device is connected." If you don't see this prompt, you may need to add the plugin to the main toolbar manually in **Preferences > Toolbars & menus** and select "The main toolbar" from the dropdown, then find "Romance.io" in the available actions and click the ">" button to add it to the toolbar.

**To get the latest version** before it's published to the plugin store, download the zip from the [GitHub releases page](https://github.com/plain-cover/calibre_plugins/releases) and install via **Preferences > Plugins > Load plugin from file**.
- `Romance.io.zip` - metadata source plugin (ID, cover, series, tags)
- `Romance.io Fields.zip` - custom columns plugin (steam, stars, vote count, tags)

## Notes

**You can process one book or many at once.** Select any number of books and click the Romance.io plugin button in the main Calibre toolbar to download in bulk. The download will run in the background and alert you when it's done. You can track the job's progress in the bottom-right corner of the Calibre window.

**A browser window may open during downloads.** The plugin tries the Romance.io JSON API first, which is fast and requires no browser. If the API is unavailable, it falls back to opening a Chrome browser window to scrape the page directly - just ignore it, it will close automatically. JSON API lookups are fast; browser-based lookups can take ~5-30 seconds per book.

**Chrome is required for the HTML-based metadata download fallback.** If Chrome is not installed, the plugin can only use the JSON API, so if that isn't available, you won't get any field data. Install Chrome from [google.com/chrome](https://www.google.com/chrome/). Chrome doesn't need to be your default browser, it just needs to be installed. On Apple Silicon Macs (M1/M2/M3/M4), Chrome's browser automation also requires Rosetta 2 - if that's missing, the plugin's job log will tell you how to install it.

**Wrong book matched, or your title/author in Calibre intentionally differs from Romance.io?** The automatic search matches by title and author - if your library uses a different edition name, spelling, or you've renamed the book, the search may fail or pick the wrong result. That's fine: you can still manually link any book to its Romance.io page. Find the book on [Romance.io](https://romance.io) and open its **book detail page** (not the series page - the URL should contain `/books/`), then copy the ID from the URL (e.g. `5484ecd47a5936fb0405756c` from `romance.io/books/5484ecd47a5936fb0405756c/...`). In Calibre, open **Edit metadata** for the book, go to the **Ids** field, and add `romanceio:5484ecd47a5936fb0405756c`. After saving, the link to Romance.io will work in the book details panel, and Romance.io Fields will be able to download data for the book.

**Tags are not downloaded in any particular order.** Calibre automatically alphabetizes tags in the tag browser, so the download order doesn't matter.

**Only English is supported for now.** If you're interested in support for another language, let me know by opening a [GitHub Issue](https://github.com/plain-cover/calibre_plugins/issues).

## Issues

[GitHub Issues](https://github.com/plain-cover/calibre_plugins/issues). Please include as much detail as possible:

- **Title and author** as they appear in Calibre, and the **expected Romance.io URL**
- **Calibre version** - shown in the bottom-left of the Calibre window, or via **Help > About Calibre**
- **Plugin version** - go to **Preferences > Plugins**, find the plugin, and note the version number shown
- **Error logs or tracebacks** - if a job fails, a pop-up will appear with the error. If not, look at the job count in the bottom-right corner of Calibre, click it, select the failed job, and click **Show job details** to see the full output. Copy and paste this into your report.

**For more verbose logs**, start Calibre in debug mode: right-click the **Preferences** button (gear icon in the toolbar) and choose **Restart in debug mode**. Log output will be printed to the terminal that opens.

## For developers

### Build and run

```bash
cd romanceio && ./build.sh
cd ../romanceio_fields && ./build.sh
calibre-debug -g
```

`build.sh` vendors dependencies and copies shared code from `common/` before zipping the plugin. Run it for both plugins before launching. See [romanceio/README.md](romanceio/README.md) and [romanceio_fields/README.md](romanceio_fields/README.md) for per-plugin build details and test commands.

### Why are dependencies bundled in the zip?

Calibre runs plugins in its own embedded Python environment - you can't install packages at runtime with pip. So all dependencies (seleniumbase, lxml, requests, etc.) are installed into the plugin folder at build time and bundled into the zip. See [common/README.md](common/README.md) for details on the shared code layer.

