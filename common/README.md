# Common Files

This folder contains shared code between the romanceio and romanceio_fields plugins.

## Files

- **common_compatibility.py** - Qt version compatibility imports (PyQt5 -> Qt6)
- **common_dialogs.py** - Common dialog base classes with position persistence
- **common_fetch_helper.py** - SeleniumBase page fetching with dynamic plugin imports
- **common_icons.py** - Icon resource management with `get_icon()` function
- **common_menus.py** - Menu building helper functions
- **common_romanceio_tag_mappings.py** - Slug-to-display-name mapping for Romance.io JSON tags (`JSON_TO_UI_TAG_MAP`, `TAGS_TO_IGNORE`, `convert_json_tags_to_display_names`)
- **common_search.py** - Romance.io search and ID extraction logic
- **common_widgets.py** - Custom Qt controls (ReadOnlyTableWidgetItem, etc.)
- **test_json_search_matching.py** - Shared test: JSON search result matching
- **test_tag_slug_conversion.py** - Shared test: slug-to-display-name conversion
- **test_html_sanitizer.py** - Shared test: `sanitize_html_for_lxml()` strips XML 1.0 illegal chars from Selenium HTML

## How it works

During the build process:

1. `build.py` copies files from `../common/` into each plugin folder
2. `build.py` adjusts imports from `from common_X` to `from calibre_plugins.<plugin_name>.common_X`
3. The modified files are included in the plugin zip

This allows both plugins to share code while maintaining proper Calibre plugin namespacing.

## Why dependencies are vendored

Calibre runs plugins in its own embedded Python environment. There's no way to install packages at runtime with pip, so all dependencies (seleniumbase, lxml, requests, fake_useragent, etc.) are installed into the plugin folder at build time via `setup_deps.sh` and bundled into the zip.

- `requirements.txt` in each plugin folder lists the dependencies
- `setup_deps.sh` runs `pip install -t .` to install them locally
- `build.sh` calls `setup_deps.sh` automatically if dependencies are missing

Never import vendored packages directly - use the plugin namespace (e.g. `calibre_plugins.romanceio.seleniumbase`) so imports resolve correctly inside Calibre's plugin isolation.

## Adding new common files

1. Create the file in this `common/` folder
2. Add the filename to the `common_files` list in `adjust_common_imports_for_plugin()` in `build_utils.py`
3. Rebuild both plugins

## Usage in plugins

Import from the common module:

```python
from .common_search import search_for_romanceio_id
```

The build process will automatically rewrite this to:

```python
from calibre_plugins.romanceio.common_search import search_for_romanceio_id
# or
from calibre_plugins.romanceio_fields.common_search import search_for_romanceio_id
```
