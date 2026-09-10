# Common Files

This folder contains shared code between the romanceio and romanceio_fields plugins.

## Files

- **common_compatibility.py** - Qt version compatibility imports (PyQt5 -> Qt6)
- **common_dialogs.py** - Common dialog base classes with position persistence
- **common_romanceio_fetch_helper.py** - HTTP fetching and supervised browser lifecycle
- **common_romanceio_session.py** - Temporary Cloudflare clearance shared by HTTP and browser requests
- **common_romanceio_transport.py** - Job-owned HTTP connections and shared lookup deadlines
- **common_romanceio_webengine.py** - Invisible page rendering with Calibre's bundled Qt WebEngine
- **common_icons.py** - Icon resource management with `get_icon()` function
- **common_menus.py** - Menu building helper functions
- **common_romanceio_tag_mappings.py** - Shared slug-to-display-name conversion and the public import point for Romance.io tag taxonomy data (`JSON_TO_UI_TAG_MAP`, `SPECIAL_TAG_CATEGORIES`, `TAGS_TO_IGNORE`)
- **common_romanceio_tag_categories.py** - Generated category mapping for Romance.io content-warning, geography, and format tags
- **check_romanceio_tag_taxonomy.py** - Weekly maintenance checker that compares the bundled taxonomy with Romance.io
- **update_tag_mappings.py** - Maintainer command that refreshes both bundled taxonomy files
- **common_romanceio_search.py** - Romance.io search and ID extraction logic
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

The display-name and category mappings are refreshed together with `python common/update_tag_mappings.py`. Builds validate the committed files but never contact Romance.io or rewrite them. The **Romance.io Tag Updates (Weekly Maintenance Check)** GitHub Actions workflow compares both mappings with the live site using HTTP first, then the installed plugin's Qt and Chrome recovery paths if needed. An access failure means the check could not run; it is not evidence that the mappings changed. A failure titled **Romance.io tag taxonomy changed** is an expected maintenance alert: run the updater, review the generated mapping changes, and commit them.

To run the same check locally, install the rebuilt Fields plugin and use `calibre-debug -e common/check_romanceio_tag_taxonomy.py -- --live --browser-fallback`. Plain `python ... --live` remains available for HTTP-only diagnostics. Exit codes distinguish a completed comparison (0), changed mappings (1), and a check that could not run (2); unavailable checks also appear in the Actions summary.

## HTTP and browser access

Search tries JSON over HTTP first. On a 403 it tries JSON and then HTML within one Qt session, followed by JSON and then HTML within one Chrome session. A known HTTP JSON 404 skips straight to browser HTML. A valid empty JSON result stops the search; an unpopulated HTML shell is a technical failure. Failed engines are not reopened by later callbacks in the same lookup. Book-detail order follows the existing `preferHtmlParsing` setting:

| Setting | Order when earlier methods fail |
|---|---|
| Unchecked (default) | HTTP → Qt WebEngine → Chrome → legacy JSON |
| Checked | Chrome → HTTP → Qt WebEngine → legacy JSON |

`fetch_page` checks cancellation before each engine. Search JSON and HTML share the same engine/profile and navigation budget. A valid book-page not-found response does not launch the next browser; an HTML error at a JSON URL fails promptly. Browser failures raise `BrowserFetchError` so the orchestrator does not repeat browser launches. HTTP 403s are remembered per endpoint in the job-owned HTTP session, so later books do not repeat the same blocked request. New browser clearance permits fresh HTTP attempts; ending the job discards this failure state. A blocked endpoint does not disable other endpoints. Cookie expiry or rejection alone does not clear the remembered failure.

The Qt backend uses Calibre's bundled Qt WebEngine (Qt 6 or PyQt5). It creates no QWebEngineView, uses an off-the-record profile, and disables page dialogs, clipboard access, and local-file access. Both backends disable direct WebRTC UDP networking and QUIC to avoid unnecessary UDP listeners. The local Qt smoke test checks for UDP sockets and externally bound TCP listeners; it does not guarantee that every firewall product will suppress prompts.

Both backends run in disposable Calibre workers. A supervisor tracks descendants and the caller's PID/creation time to clean up after cancellation, caller death, or timeout. Each search or detail operation has a 120-second active-work budget across HTTP retries and browser recovery. The existing 6-second JSON spacing, 15-second rate-limit retry delay and 60-second cooldown remain unchanged and do not consume that budget. These waits still check cancellation every half second; ordinary transient retry delays continue to count toward the budget. Qt is capped at 45 seconds and Chrome at 90 seconds, reduced to the remaining lookup budget, including driver setup. Cleanup may take several additional seconds. A batch can contain many independently bounded operations. Progress is streamed into the job log. Fields downloads run within their existing Calibre job without a nested book-worker pool.

HTTP 429s from JSON and book HTML use the same retry policy: up to three attempts, waiting at least 15 seconds between attempts. A valid `Retry-After` delay or HTTP-date extends that wait when necessary; missing or malformed values use the tuned defaults. Fallback methods (including browser startup) and subsequent books wait until at least 60 seconds after the last 429, or the server's later deadline. This state is shared within a plugin's job process, not globally across separate Calibre processes. Waits are logged, remain cancellable, and do not consume the active-work budget. A 429 does not discard clearance or enter the 403/404 failure caches.

Exhausted searches raise `SearchFailedError`; metadata identify reports an error to Calibre instead of claiming no match. Live test adapters reject lookup errors and cancellation. Actions summarizes live outcomes separately from required deterministic checks. Browser setup restores stdout, stderr, and the exception hook as well as import state: repeated SeleniumBase imports otherwise accumulate Colorama stream wrappers and eventually make logging raise `RecursionError`.

`common_romanceio_transport.py` owns a reusable HTTPS connection per job thread. It uses standard verified TLS, urllib-compatible header casing, a stable User-Agent, and keep-alive. Configured HTTPS proxies retain urllib's existing behavior. Idle connections expire after 30 seconds and close when the job ends. Direct and proxy response reads are size-limited, reject truncated bodies, and check cancellation/deadlines between chunks. Only `__cf_bm` is retained in memory for bot-session continuity, respecting its lifetime and origin; login/analytics cookies are ignored. HTTP status, challenge markers, elapsed time and connection reuse are logged without cookie values.

Either browser can save temporary clearance after validated access for later HTTP requests, including a separate Fields job. Error/404 pages do not replace a proven clearance cache. `common_romanceio_session.py` saves only `cf_clearance`, its User-Agent, and an expiry capped at 30 minutes in the existing `CALIBRE_SELENIUM_HOME` cache location. Login cookies are not saved. Writes are atomic and private on POSIX; malformed, expired, or rejected clearance is discarded. Cookies are sent only to `https://www.romance.io`, and cross-origin redirects carrying them are refused. Clearance is not guaranteed to be issued or accepted.

After installing both release ZIPs into an isolated Calibre configuration, run from the repository root:

```bash
calibre-debug -e common/run_installed_browser_smoke.py -- romanceio_fields --search-routes
calibre-debug -e common/run_installed_browser_smoke.py -- romanceio_fields --search-routes --backend chrome --driver-source managed
calibre-debug -e common/run_installed_browser_smoke.py -- romanceio_fields --search-routes --chrome-fallback --driver-source managed
calibre-debug -e common/run_installed_browser_lifecycle.py -- cancel
calibre-debug -e common/run_installed_browser_lifecycle.py -- timeout
calibre-debug -e common/run_installed_live_smoke.py -- json-clearance-reuse
```

The local smoke checks rendering and cleanup. `--backend chrome` requires Chrome and fails if Qt is attempted; `--chrome-fallback` simulates Qt failure and requires the real Chrome worker to succeed. CI seeds the runner's driver by default; `--driver-source managed` uses the plugin's normal driver cache/download path. Chrome launch coverage runs alongside Qt on current desktops, Calibre 5, and Flatpak; Linux ARM instead checks that unsupported Chrome setup fails safely. The lifecycle checks use a stalled local server. The live clearance check reports whether fresh challenge clearance was actually exercised, then requires HTTP-only search and details. Live site outcomes are non-blocking in CI; local rendering, cleanup, and package checks are required.

## Why dependencies are vendored

Calibre runs plugins in its own embedded Python environment. There's no way to install packages at runtime with pip, so pure-Python browser dependencies (seleniumbase, requests, fake_useragent, etc.) are installed into the plugin folder at build time via `setup_deps.sh` and bundled into the zip. Native packages such as `lxml` and `psutil` deliberately come from Calibre's cross-platform runtime; bundling a wheel from the maintainer's computer would make the same plugin zip fail on other operating systems.

- `requirements.txt` lists packages shared by all runtimes; the other `requirements-*.txt` manifests match SeleniumBase's Python 3.8, 3.9, and current-Python dependency branches
- Every vendored requirement is SHA-256 locked, and `setup_deps.sh` uses pip's `--require-hashes` mode while installing platform-neutral wheels below `browser_vendor/`; the helper selects the correct branch before importing SeleniumBase
- `build.sh` validates every vendor branch and a content fingerprint covering all dependency manifests plus `setup_deps.sh`; it rebuilds dependencies whenever either changes
- ChromeDriver remains a runtime download because it must match the user's installed Chrome. Google's Chrome-for-Testing APIs do not currently publish authoritative checksums, so the helper refuses SeleniumBase's HTTP downgrade behavior, permits only explicit Google HTTPS origins (including redirects), and records the downloaded cache executable's SHA-256 digest atomically. A cross-process lock serializes installation, integrity recovery, Chrome-major-version refreshes, and copying from the shared cache. Each browser worker checks that local baseline, rebuilds the patched UC executable in its own temporary directory, and checks the launch-time bytes. The adjacent digest detects corruption and races but is not an independent provenance guarantee; the first download still depends on Google's TLS endpoint.
- Calibre's Flatpak build can use direct HTTP and its bundled Qt WebEngine. Launchers belonging to a separate browser Flatpak are not treated as normal browser binaries because they depend on that application's own `/app` runtime; candidate direct binaries must pass an execution probe before Selenium receives them.
- Linux ARM is detected before browser setup because Chrome for Testing does not publish a Linux ARM ChromeDriver. The Chrome path is skipped without downloading an x86_64 executable; Qt WebEngine and direct HTTP remain available.
- `build_utils.py` uses an explicit release-folder allowlist and recursively excludes command launchers, development helpers, caches, and native extension files
- Runtime `.dist-info` metadata is preserved, and a scoped metadata finder exposes it from the selected branch inside the plugin ZIP
- The one ZIP contains SeleniumBase 4.44.20 for Calibre 5 and SeleniumBase 4.52.4 for current Calibre, each with its declared dependency versions
- `build_utils.py` adds package markers for every ancestor required by Calibre 5's older zip importer
- Local builds and `test_release_zip.py` require every plugin ZIP to remain strictly smaller than the 40 MB distribution limit
- `test_release_zip.py` also audits portability and minimum-version syntax; `test_release_zip_imports.py` imports the browser stack inside current Calibre, Calibre 5, and the Calibre Flatpak, and checks shared modules and the full Chrome startup import path under a standalone Python 3.9 interpreter (`--skip-qt` omits only Qt imports)

Browser imports must go through `common_romanceio_fetch_helper`. Installed plugins perform the browser work in a disposable Calibre worker, so temporary changes to `sys.path`, `sys.meta_path`, `sys.modules`, and `PATH` never affect unrelated Calibre threads. The parent receives only the fetched HTML and redacted log messages.

## Adding new common files

1. Create the file in this `common/` folder
2. Add the filename to the `common_files` list in `adjust_common_imports_for_plugin()` in `build_utils.py`
3. Rebuild both plugins

## Usage in plugins

Import from the common module:

```python
from .common_romanceio_search import search_for_romanceio_id
```

This relative import resolves within the installed plugin package. The build also rewrites absolute `from common_...` imports to the corresponding `calibre_plugins.<plugin_name>` namespace.
