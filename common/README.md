# Common Files

This folder contains shared code between the romanceio and romanceio_fields plugins.

## Files

- **common_compatibility.py** - Qt version compatibility imports (PyQt5 -> Qt6)
- **common_dialogs.py** - Common dialog base classes with position persistence
- **common_fetch_helper.py** - SeleniumBase page fetching with dynamic plugin imports
- **common_icons.py** - Icon resource management with `get_icon()` function
- **common_menus.py** - Menu building helper functions
- **common_romanceio_tag_mappings.py** - Shared slug-to-display-name conversion and the public import point for Romance.io tag taxonomy data (`JSON_TO_UI_TAG_MAP`, `SPECIAL_TAG_CATEGORIES`, `TAGS_TO_IGNORE`)
- **common_romanceio_tag_categories.py** - Generated category mapping for Romance.io content-warning, geography, and format tags
- **check_romanceio_tag_taxonomy.py** - Weekly maintenance checker that compares the bundled taxonomy with Romance.io
- **update_tag_mappings.py** - Maintainer command that refreshes both bundled taxonomy files
- **common_search.py** - Romance.io search and ID extraction logic
- **common_widgets.py** - Custom Qt controls (ReadOnlyTableWidgetItem, etc.)
- **test_json_search_matching.py** - Shared test: JSON search result matching
- **test_tag_slug_conversion.py** - Shared test: slug-to-display-name conversion
- **test_romanceio_tag_taxonomy.py** - Tests the taxonomy checker and transactional mapping updater
- **test_html_sanitizer.py** - Shared test: `sanitize_html_for_lxml()` strips XML 1.0 illegal chars from Selenium HTML

## How it works

During the build process:

1. `build.py` copies files from `../common/` into each plugin folder
2. `build.py` adjusts imports from `from common_X` to `from calibre_plugins.<plugin_name>.common_X`
3. The modified files are included in the plugin zip

This allows both plugins to share code while maintaining proper Calibre plugin namespacing.

The display-name and category mappings are refreshed together with `python common/update_tag_mappings.py`. Builds validate the committed files but never contact Romance.io or rewrite them. The **Romance.io Tag Updates (Weekly Maintenance Check)** GitHub Actions workflow compares both mappings with the live site using plain HTTP. A failure titled **Romance.io tag taxonomy changed** is an expected maintenance alert: run the updater, review the generated mapping changes, and commit them.

## Why dependencies are vendored

Calibre runs plugins in its own embedded Python environment. There's no way to install packages at runtime with pip, so pure-Python browser dependencies (seleniumbase, requests, fake_useragent, etc.) are installed into the plugin folder at build time via `setup_deps.sh` and bundled into the zip. Native packages such as `lxml` and `psutil` deliberately come from Calibre's cross-platform runtime; bundling a wheel from the maintainer's computer would make the same plugin zip fail on other operating systems.

- `requirements.txt` lists packages shared by all runtimes; the other `requirements-*.txt` manifests match SeleniumBase's Python 3.8, 3.9, and current-Python dependency branches
- Every vendored requirement is SHA-256 locked, and `setup_deps.sh` uses pip's `--require-hashes` mode while installing platform-neutral wheels below `browser_vendor/`; the helper selects the correct branch before importing SeleniumBase
- `build.sh` validates every vendor branch and a content fingerprint covering all dependency manifests plus `setup_deps.sh`; it rebuilds dependencies whenever either changes
- ChromeDriver remains a runtime download because it must match the user's installed Chrome. Google's Chrome-for-Testing APIs do not currently publish authoritative checksums, so the helper refuses SeleniumBase's HTTP downgrade behavior, permits only explicit Google HTTPS origins (including redirects), and records the downloaded cache executable's SHA-256 digest atomically. A cross-process lock serializes installation, integrity recovery, Chrome-major-version refreshes, and copying from the shared cache. Each browser worker checks that local baseline, rebuilds the patched UC executable in its own temporary directory, and checks the launch-time bytes. The adjacent digest detects corruption and races but is not an independent provenance guarantee; the first download still depends on Google's TLS endpoint.
- Calibre's Flatpak build remains supported through JSON search and lightweight webpage fetching. Launchers belonging to a separate browser Flatpak are not treated as normal browser binaries because they depend on that application's own `/app` runtime; candidate direct binaries must pass an execution probe before Selenium receives them.
- Linux ARM is detected before browser setup because Chrome for Testing does not publish a Linux ARM ChromeDriver. The unsupported browser path is skipped without downloading an x86_64 executable; JSON and lightweight HTTP metadata remain available.
- `build_utils.py` uses an explicit release-folder allowlist and recursively excludes command launchers, development helpers, caches, and native extension files
- Runtime `.dist-info` metadata is preserved, and a scoped metadata finder exposes it from the selected branch inside the plugin ZIP
- The one ZIP contains SeleniumBase 4.44.20 for Calibre 5 and SeleniumBase 4.52.4 for current Calibre, each with its declared dependency versions
- `build_utils.py` adds package markers for every ancestor required by Calibre 5's older zip importer
- Local builds and `test_release_zip.py` require every plugin ZIP to remain strictly smaller than the 40 MB distribution limit
- `test_release_zip.py` also audits portability and minimum-version syntax; `test_release_zip_imports.py` imports the browser stack inside current Calibre, Calibre 5, and the Calibre Flatpak, and imports the complete production module path under an actual standalone Python 3.9 interpreter

Browser imports must go through `common_romanceio_fetch_helper`. Installed plugins perform the browser work in a disposable Calibre worker, so temporary changes to `sys.path`, `sys.meta_path`, `sys.modules`, and `PATH` never affect unrelated Calibre threads. The parent receives only the fetched HTML and redacted log messages.

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
