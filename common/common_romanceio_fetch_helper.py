"""
Shared helper for fetching pages with SeleniumBase.
Used by both romanceio and romanceio_fields plugins.
"""

import glob
import importlib
import importlib.abc
import os
import platform
import random
import re
import shutil
import sys
import tempfile
import time
import types
from typing import Callable, Optional, Sequence

# List of vendored packages that need import redirection
VENDORED_PACKAGES = [
    "certifi",
    "charset_normalizer",
    "colorama",
    "cssselect",
    "fake_useragent",
    "fasteners",
    "idna",
    "lxml",
    "mycdp",
    "requests",
    "sbvirtualdisplay",
    "selenium",
    "seleniumbase",
    "six",
    "typing_extensions",
    "urllib3",
    "websocket",
    "websocket_client",
    "websockets",
]


class VendoredModule(types.ModuleType):
    """Custom module class with __getattr__ for dynamic submodule loading"""

    def __init__(self, name, finder, real_name=None):
        super().__init__(name)
        self._finder = finder
        self._real_name = real_name
        self.__package__ = ".".join(name.split(".")[:-1]) if "." in name else name
        self.__path__ = []

    def __getattr__(self, name):
        """Dynamically load submodules when accessed"""
        if name.startswith("_"):
            raise AttributeError(f"module '{self.__name__}' has no attribute '{name}'")

        submodule_name = f"{self.__name__}.{name}"
        if submodule_name not in sys.modules:
            try:
                self._finder.load_module(submodule_name)
            except ImportError as exc:
                raise AttributeError(f"module '{self.__name__}' has no attribute '{name}'") from exc

        return sys.modules.get(submodule_name)


class VendoredPackageFinder(importlib.abc.MetaPathFinder):
    """Find vendored packages and handle circular imports by creating module aliases"""

    def __init__(self, plugin_name, packages=None, plugin_dir=None):
        self.plugin_name = plugin_name
        self.plugin_dir = plugin_dir
        self.plugin_prefix = f"calibre_plugins.{plugin_name}"
        # Build map of package names to their prefixes
        self.packages = {pkg: f"{self.plugin_prefix}.{pkg}" for pkg in (packages or VENDORED_PACKAGES)}

    def find_module(self, fullname: str, _path: Optional[Sequence[str]] = None) -> Optional["VendoredPackageFinder"]:  # type: ignore[override]
        """Check if this is a vendored package import that needs redirection."""
        package_name = fullname.split(".")[0]
        return self if package_name in self.packages else None

    def load_module(self, fullname: str) -> types.ModuleType:
        """Load module and register under both real and alias names"""
        # Only early-return for modules that are fully initialized.
        # When called from Python's find_spec backward-compat path, _installed_safely
        # pre-inserts an empty types.ModuleType into sys.modules before calling us.
        # Returning that placeholder would break all subsequent submodule imports.
        # We distinguish real/placeholder by checking for our own VendoredModule marker.
        existing = sys.modules.get(fullname)
        if existing is not None and isinstance(existing, VendoredModule):
            # Our own re-entrancy placeholder - return to prevent infinite recursion
            return existing
        if existing is not None and getattr(existing, "__file__", None) is not None:
            # Fully-loaded module (has __file__) - safe to reuse
            return existing

        # Ensure parent module is loaded first
        if "." in fullname:
            parent_name = fullname.rsplit(".", 1)[0]
            if parent_name not in sys.modules:
                self.load_module(parent_name)

        # Map alias to real module path
        package_name = fullname.split(".")[0]
        if package_name not in self.packages:
            raise ImportError(f"Package {package_name} not in vendored packages")

        package_prefix = self.packages[package_name]
        if fullname == package_name:
            real_name = package_prefix
        else:
            parts = fullname.split(".", 1)
            real_name = f"{package_prefix}.{parts[1]}"

        # Return existing module if already loaded
        if real_name in sys.modules:
            sys.modules[fullname] = sys.modules[real_name]
            if "." in fullname:
                parent_name, attr_name = fullname.rsplit(".", 1)
                if parent_name in sys.modules:
                    setattr(sys.modules[parent_name], attr_name, sys.modules[fullname])
            return sys.modules[fullname]

        # Create placeholder module that Python recognizes as a package
        placeholder = VendoredModule(fullname, self, real_name)
        # Set __path__ for top-level packages so Python can find submodules via zipimport.
        # Without this, __path__=[] forces ALL seleniumbase sub-imports back through
        # VendoredPackageFinder, which redirects to calibre_plugins.romanceio.seleniumbase.*
        # via calibre's own hook.  On calibre 8.x that redirect fails for deeply nested
        # names (e.g. seleniumbase.core.browser_launcher), producing the misleading
        # "No module named 'seleniumbase'" SeleniumBaseImportError even though the top-
        # level package is present.  A proper __path__ lets Python use zipimport directly
        # for all intra-package sub-imports, bypassing the problematic redirect entirely.
        if self.plugin_dir and "." not in fullname:
            # zipimport expects 'zip_file_path/package_name' with a forward slash
            placeholder.__path__ = [self.plugin_dir + "/" + fullname]
        sys.modules[fullname] = placeholder

        try:
            imported = importlib.import_module(real_name)
            sys.modules[fullname] = imported
            sys.modules[real_name] = imported

            # Set as attribute on parent module
            if "." in fullname:
                parent_name, attr_name = fullname.rsplit(".", 1)
                setattr(sys.modules[parent_name], attr_name, imported)

            return imported
        except Exception as _primary_exc:
            # Clean up ALL partially-loaded submodules, not just the top-level.
            # When loading a heavy package like seleniumbase, __init__.py may
            # partially succeed before failing deep in its import chain, leaving
            # stale half-initialized submodules in sys.modules.  If we only
            # remove the top-level package, the zipimport fallback below will
            # re-run __init__.py which then finds these stale submodules and
            # fails too, producing a confusing 'No module named ...' error that
            # hides the real cause.
            for _mod_name in [k for k in list(sys.modules) if k == real_name or k.startswith(real_name + ".")]:
                sys.modules.pop(_mod_name, None)
            for _mod_name in [k for k in list(sys.modules) if k == fullname or k.startswith(fullname + ".")]:
                sys.modules.pop(_mod_name, None)
            # NOTE: intentionally NOT calling importlib.invalidate_caches() here.
            # On Windows, Calibre may hold the plugin zip open; invalidate_caches()
            # forces zipimport to close and re-open the zip, which can raise a
            # PermissionError and cause the fallback to fail with a misleading
            # "No module named '...'" even though the zip content is fine.
            # Redirect via calibre_plugins namespace failed (e.g. in calibre GUI mode).
            # Fall back to a direct import via sys.path so zipimport can handle it.
            # Import the full dotted name (not just the top-level package) so submodules
            # like 'seleniumbase.fixtures.constants' are resolved correctly.
            was_in = self in sys.meta_path
            if was_in:
                sys.meta_path.remove(self)  # type: ignore[arg-type]
            try:
                imported = importlib.import_module(fullname)
                sys.modules[fullname] = imported
                sys.modules[real_name] = imported
                if "." in fullname:
                    parent_name, attr_name = fullname.rsplit(".", 1)
                    if parent_name in sys.modules:
                        setattr(sys.modules[parent_name], attr_name, imported)
                return imported
            except Exception as _fallback_exc:
                # Preserve the original (primary) exception as __cause__ so it
                # appears in tracebacks and can be logged in fetch_page.
                raise ImportError(f"No module named {fullname!r}") from _primary_exc
            finally:
                if was_in:
                    sys.meta_path.insert(0, self)  # type: ignore[arg-type]


class ChromeNotInstalledError(RuntimeError):
    """Raised when Chrome is not installed on the system.  Not retryable."""


class RosettaNotInstalledError(RuntimeError):
    """Raised on Apple Silicon Macs when Rosetta 2 is missing and UC Mode cannot run.  Not retryable."""


class SeleniumBaseImportError(RuntimeError):
    """Raised when seleniumbase cannot be imported in the current process context.  Not retryable."""


# XML 1.0 §2.2: legal chars are #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
# Everything else is illegal and causes lxml to raise XMLSyntaxError: internal error.
# Selenium's page_source is a DOM serialization - the browser decodes HTML entities before
# serializing, so characters that were safely entity-encoded in the raw server HTML (e.g. &#x0B;)
# become literal control characters in the returned string.
_XML10_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def sanitize_html_for_lxml(html: str) -> str:
    """Strip XML 1.0 illegal chars and lone surrogates from a Selenium page_source string.

    Returns a clean str with all XML 1.0 illegal characters removed and lone surrogates
    replaced with U+FFFD via a UTF-8 round-trip.

    NOTE: Do NOT pass the result of this function to bare lxml.html.fromstring() --
    that can still raise XMLSyntaxError: internal error on Windows due to lxml's internal
    str-to-bytes conversion path. Use parse_html_from_selenium() instead, which passes
    bytes with an explicit HTMLParser(encoding="utf-8") to bypass that path entirely.

    This function is retained as a standalone sanitizer for contexts that need a clean
    str without immediately parsing it.
    """
    cleaned = _XML10_ILLEGAL_CHARS_RE.sub("", html)
    # Round-trip through UTF-8 to replace any lone surrogates with U+FFFD
    return cleaned.encode("utf-8", errors="replace").decode("utf-8")


def parse_html_from_selenium(html: str) -> "lxml.html.HtmlElement":  # type: ignore[name-defined]
    """Parse Selenium page_source HTML safely with lxml.

    Strips XML 1.0 illegal chars and lone surrogates, then parses using
    lxml.html.HTMLParser(encoding="utf-8") with bytes. This bypasses the
    PyUnicode_AsUTF8AndSize str-encoding path that can produce
    XMLSyntaxError: internal error for certain characters that libxml2
    rejects even after str sanitization (e.g. C1 control chars like \\x85
    in specific HTML positions). Passing bytes with an explicit encoding
    forces libxml2 to use its own UTF-8 decode path which has better recovery.

    Returns:
        lxml.html.HtmlElement: parsed document root
    """
    from lxml.html import HTMLParser, fromstring as _html_fromstring  # local import - lxml may be vendored

    cleaned = _XML10_ILLEGAL_CHARS_RE.sub("", html)
    html_bytes = cleaned.encode("utf-8", errors="replace")
    parser = HTMLParser(encoding="utf-8")
    return _html_fromstring(html_bytes, parser=parser)


def _find_flatpak_chrome() -> Optional[str]:
    """Return the Chrome/Chromium binary installed as a flatpak, or None.

    Works whether Calibre itself is a flatpak or not.  The flatpak directory
    structure includes architecture and branch levels that vary by system
    (e.g. /var/lib/flatpak/app/com.google.Chrome/x86_64/stable/active/...),
    so glob wildcards are used to handle those levels automatically.

    Requires the flatpak app directories to be visible on the filesystem.
    If Calibre is also a flatpak, the user must first run:
        flatpak override --user com.calibre_ebook.calibre --filesystem=host
    """
    if platform.system() != "Linux":
        return None

    app_bases = [
        os.path.join(os.path.expanduser("~"), ".local", "share", "flatpak", "app"),
        "/var/lib/flatpak/app",
    ]
    # (flatpak app id, path to binary relative to the active install root)
    candidates = [
        ("com.google.Chrome", "files/extra/google-chrome"),
        ("com.google.ChromeDev", "files/extra/google-chrome"),
        ("org.chromium.Chromium", "files/bin/chromium"),
    ]
    for base in app_bases:
        for app_id, rel_path in candidates:
            # Use * for arch (e.g. x86_64) and branch (e.g. stable) levels
            pattern = os.path.join(base, app_id, "*", "*", "active", rel_path)
            for match in glob.glob(pattern):
                if os.access(match, os.X_OK):
                    return match
    return None


def log_system_info(log_func: Optional[Callable[[str], None]] = None) -> None:
    """Log OS, Python, and Calibre version. Call once at the start of each job."""

    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    try:
        from calibre.constants import numeric_version as _calibre_version

        _calibre_version_str = ".".join(str(x) for x in _calibre_version)
    except Exception:  # pylint: disable=broad-except
        _calibre_version_str = "unknown"
    _log(
        f"System info: OS={platform.system()} {platform.release()} "
        f"({platform.version()}), Python={platform.python_version()}, "
        f"Calibre={_calibre_version_str}"
        + (f", FLATPAK_ID={os.environ['FLATPAK_ID']}" if os.environ.get("FLATPAK_ID") else "")
    )


# Guard so the one-time stale profile cleanup only runs once per process,
# not on every fetch_page call (could block for minutes if 250GB accumulated).
_stale_profile_cleanup_done = False


def fetch_page(
    url,
    plugin_name,
    wait_for_element=None,
    not_found_marker=None,
    secondary_wait_element=None,
    max_wait=30,
    log_func=None,
):
    """
    Fetch a page using SeleniumBase with Cloudflare bypass.

    IMPORTANT: This function carefully manages SeleniumBase paths to avoid Windows
    permission errors. The constants module MUST be imported and patched BEFORE
    importing any other SeleniumBase modules. This prevents dependencies (like
    fasteners) from capturing default relative paths ("downloaded_files") which
    cause "[WinError 5] Access is denied" when converted to bytes on Windows.

    Args:
        url: URL to fetch
        plugin_name: Name of the plugin ('romanceio' or 'romanceio_fields') for imports
        wait_for_element: Optional element to wait for in page source
        not_found_marker: Optional string; if found in the page while waiting for
            wait_for_element, return the page immediately instead of timing out.
            Useful to avoid waiting the full timeout when a 404 / not-found page
            is returned (which will never contain wait_for_element).
        secondary_wait_element: Optional string; after wait_for_element is found,
            continue polling until this element also appears (or time runs out).
            Unlike wait_for_element, the page is returned whether or not this
            element appears - it just buys more time for JS rendering. Use this
            when wait_for_element is an SSR container and secondary_wait_element
            is the JS-rendered content inside it (e.g. search result items).
        max_wait: Maximum seconds to wait for page load
        log_func: Optional logging function to route errors to calibre's job log

    Returns:
        Page HTML as string, or None on error
    """

    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    user_data_dir = None
    try:
        # Use a stable driver directory under the user's home dir so chromedriver
        # persists across calibre sessions (calibre rotates its own temp dir each run)
        stable_base = os.path.join(os.path.expanduser("~"), ".calibre_selenium")
        sb_drivers_dir = os.path.abspath(os.path.join(stable_base, "drivers"))
        downloads_dir = os.path.abspath(os.path.join(stable_base, "downloads"))

        # Each Chrome instance gets a fresh throw-away profile in the system TEMP dir.
        # Using TEMP (not stable_base) keeps paths short (avoids Windows MAX_PATH issues)
        # and ensures the OS auto-cleans these on reboot even if we crash before cleanup.
        # The directory is removed in the finally block below after driver.quit().
        user_data_dir = tempfile.mkdtemp(prefix="calibre_sb_")

        # One-time best-effort cleanup of stale profile dirs left by older plugin versions
        # that used ~/.calibre_selenium/user_data/profile_<pid>_<ts>/ and never deleted them.
        # Only runs once per process to avoid blocking every fetch when 250GB+ is accumulated.
        global _stale_profile_cleanup_done
        if not _stale_profile_cleanup_done:
            _stale_profile_cleanup_done = True
            _old_user_data_root = os.path.join(stable_base, "user_data")
            if os.path.isdir(_old_user_data_root):
                _now = time.time()
                for _entry in os.listdir(_old_user_data_root):
                    if _entry.startswith("profile_"):
                        _entry_path = os.path.join(_old_user_data_root, _entry)
                        try:
                            _mtime = os.path.getmtime(_entry_path)
                            # Only remove dirs that haven't been touched in the last 2 hours
                            # (leaves any dir that might belong to a concurrently running instance)
                            if _now - _mtime > 7200:
                                shutil.rmtree(_entry_path, ignore_errors=True)
                        except OSError:
                            pass  # ignore - best effort only

        # Ensure persistent directories exist
        for dir_path in [sb_drivers_dir, downloads_dir]:
            os.makedirs(dir_path, exist_ok=True)

        # Add the plugin directory to sys.path NOW (before module clearing and
        # before VendoredPackageFinder is set up) so the zip is on sys.path from
        # the start.  VendoredPackageFinder's zipimport fallback needs the zip
        # on sys.path to find vendored packages when the calibre_plugins.*
        # redirect fails.  Doing this early prevents a timing window where the
        # fallback runs before the zip is discoverable.
        _plugin_dir_early = os.path.dirname(os.path.abspath(__file__))
        if _plugin_dir_early not in sys.path:
            sys.path.insert(0, _plugin_dir_early)

        # Clear cached SeleniumBase/fasteners modules to ensure fresh import.
        # Clear both the calibre_plugins.{plugin_name}.* namespace AND the bare
        # selenium/seleniumbase namespace - the latter is used when the zip is on sys.path.
        _sb_prefixes = (
            f"calibre_plugins.{plugin_name}.seleniumbase",
            f"calibre_plugins.{plugin_name}.fasteners",
            "seleniumbase",
            "selenium",
            "fasteners",
            "mycdp",
            "websockets",
            "websocket",
        )
        cached_sb_modules = [key for key in list(sys.modules) if key.startswith(_sb_prefixes)]
        for module_name in cached_sb_modules:
            del sys.modules[module_name]

        # Install import hook for vendored packages if not already installed
        # Check if we already have a finder for this plugin
        existing_finder = None
        for meta_finder in sys.meta_path:
            if isinstance(meta_finder, VendoredPackageFinder) and meta_finder.plugin_name == plugin_name:
                existing_finder = meta_finder
                break

        if not existing_finder:
            finder: VendoredPackageFinder = VendoredPackageFinder(plugin_name, plugin_dir=_plugin_dir_early)  # type: ignore[assignment]
            sys.meta_path.insert(0, finder)  # type: ignore[arg-type]

        # Add the plugin's package directory to sys.path so vendored packages
        # can be imported directly via zipimport. This is required in calibre GUI
        # mode where the plugin is loaded from a zip that isn't on sys.path.
        #
        # Key insight: vendored packages (seleniumbase/, selenium/, …) sit ALONGSIDE
        # this file (common_romanceio_fetch_helper.py) inside the plugin zip.
        # Using __file__ of the current module is always correct because it doesn't
        # depend on how calibre's child IPC process sets plugin module attributes
        # (__file__ / __path__ on calibre_plugins.X point to the zip root in child
        # processes, not the plugin subdir inside it, causing ImportError).
        # NOTE: also inserted early (before module clearing) as _plugin_dir_early above.
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        _log(f"Vendored import path: {plugin_dir!r}")
        # Guard evaluates to False here (path already inserted as _plugin_dir_early above),
        # but kept for safety in case __file__ resolves differently at this point.
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        # Import and patch constants FIRST to avoid Windows permission errors.
        #
        # Strategy: try a direct zipimport (no VendoredPackageFinder) first.
        # On Calibre 8.x the calibre_plugins.* redirect in VendoredPackageFinder can
        # fail for deeply-nested modules such as seleniumbase.core.browser_launcher
        # because every sub-dependency (fasteners, selenium, mycdp, …) is also
        # intercepted and the cascade of redirects breaks when any one of them
        # cannot be resolved via the calibre_plugins namespace.  Pure zipimport from
        # the zip on sys.path is simpler and more reliable for pure-Python packages.
        #
        # VendoredPackageFinders are removed temporarily for the direct attempt, then
        # re-inserted at LOW priority (append) so C-extension packages like lxml.etree
        # (which cannot be loaded directly from a zip) still reach VendoredPackageFinder
        # after path-based finders fail.
        _vpf_saved = [f for f in list(sys.meta_path) if isinstance(f, VendoredPackageFinder)]
        for _f in _vpf_saved:
            sys.meta_path.remove(_f)  # type: ignore[arg-type]
        try:
            constants = importlib.import_module("seleniumbase.fixtures.constants")
            _log("seleniumbase: loaded via direct zipimport")
        except Exception as _direct_exc:
            _log(
                f"seleniumbase: direct zipimport failed ({type(_direct_exc).__name__}: {_direct_exc}), retrying with VendoredPackageFinder..."
            )
            # Restore VendoredPackageFinders at high priority and try via calibre_plugins.* redirect
            for _f in _vpf_saved:
                sys.meta_path.insert(0, _f)  # type: ignore[arg-type]
            # Clear all stale partial state from the failed direct attempt
            for _k in [k for k in list(sys.modules) if k.startswith(_sb_prefixes)]:
                sys.modules.pop(_k, None)
            constants = importlib.import_module("seleniumbase.fixtures.constants")
        else:
            # Direct import succeeded.  Re-add VendoredPackageFinders at LOW priority
            # so they are only invoked when path-based finders (including zipimport)
            # fail - i.e. for C extensions like lxml.etree that cannot be zipimported.
            for _f in _vpf_saved:
                sys.meta_path.append(_f)  # type: ignore[arg-type]

        # Patch Files constants immediately
        constants.Files.DOWNLOADS_FOLDER = downloads_dir
        constants.Files.ARCHIVED_DOWNLOADS_FOLDER = os.path.join(tempfile.gettempdir(), "sb_archived")

        # Patch all MultiBrowser constants that were set at class definition time
        # This prevents relative paths from being converted to problematic bytes on Windows
        constants.MultiBrowser.DRIVER_FIXING_LOCK = os.path.join(downloads_dir, "driver_fixing.lock")
        constants.MultiBrowser.DRIVER_REPAIRED = os.path.join(downloads_dir, "driver_fixed.lock")
        constants.MultiBrowser.CERT_FIXING_LOCK = os.path.join(downloads_dir, "cert_fixing.lock")
        constants.MultiBrowser.DOWNLOAD_FILE_LOCK = os.path.join(downloads_dir, "downloading.lock")
        constants.MultiBrowser.FILE_IO_LOCK = os.path.join(downloads_dir, "file_io.lock")
        constants.MultiBrowser.PYAUTOGUILOCK = os.path.join(downloads_dir, "pyautogui.lock")

        # Patch any other constants that might use relative paths
        # Iterate through MultiBrowser attributes to catch future additions
        for attr_name in dir(constants.MultiBrowser):
            if not attr_name.startswith("_"):  # Skip private attributes
                attr_value = getattr(constants.MultiBrowser, attr_name)
                # If it's a string that looks like a relative lock file path, make it absolute
                if isinstance(attr_value, str) and ("downloaded_files" in attr_value or attr_value.endswith(".lock")):
                    # Extract just the filename and recreate as absolute path
                    filename = os.path.basename(attr_value)
                    setattr(
                        constants.MultiBrowser,
                        attr_name,
                        os.path.join(downloads_dir, filename),
                    )

        # Now import other modules - they will pick up the patched constants
        sb_install = importlib.import_module("seleniumbase.console_scripts.sb_install")
        download_helper = importlib.import_module("seleniumbase.core.download_helper")
        patcher = importlib.import_module("seleniumbase.undetected.patcher")

        sb_install.DRIVER_DIR = sb_drivers_dir  # type: ignore[attr-defined]
        download_helper.downloads_path = downloads_dir  # type: ignore[attr-defined]
        patcher.Patcher.data_path = sb_drivers_dir

        browser_launcher = importlib.import_module("seleniumbase.core.browser_launcher")

        is_windows = platform.system() == "Windows"
        uc_driver_name = "uc_driver.exe" if is_windows else "uc_driver"
        undetected_name = "undetected_chromedriver.exe" if is_windows else "undetected_chromedriver"
        chromedriver_name = "chromedriver.exe" if is_windows else "chromedriver"

        # browser_launcher.py computes DRIVER_DIR from drivers.__file__ at import time.
        # When loaded from a zip, drivers.__file__ is a virtual path inside the zip,
        # not a real directory.  Patch DRIVER_DIR to our stable real directory and
        # repair os.environ["PATH"] accordingly.
        old_driver_dir = getattr(browser_launcher, "DRIVER_DIR", None)
        browser_launcher.DRIVER_DIR = sb_drivers_dir  # type: ignore[attr-defined]
        if old_driver_dir and old_driver_dir != sb_drivers_dir:
            path_env = os.environ.get("PATH", "")
            path_env = path_env.replace(old_driver_dir + os.pathsep, "")
            path_env = path_env.replace(old_driver_dir, "")
            if sb_drivers_dir not in path_env:
                path_env = sb_drivers_dir + os.pathsep + path_env
            os.environ["PATH"] = path_env

        browser_launcher.LOCAL_UC_DRIVER = os.path.join(sb_drivers_dir, uc_driver_name)  # type: ignore[attr-defined]
        browser_launcher.LOCAL_CHROMEDRIVER = os.path.join(sb_drivers_dir, chromedriver_name)  # type: ignore[attr-defined]

        # Install chromedriver if needed (SeleniumBase downloads it as "chromedriver")
        chromedriver_path = os.path.join(sb_drivers_dir, chromedriver_name)
        uc_driver_path = os.path.join(sb_drivers_dir, uc_driver_name)

        if not os.path.exists(chromedriver_path):
            _log(f"chromedriver not found at {chromedriver_path!r}, downloading...")
            sb_install.main("chromedriver latest")
            if os.path.exists(chromedriver_path):
                _log(f"chromedriver downloaded successfully")
            else:
                _log(
                    f"chromedriver download failed - file missing after install attempt: {chromedriver_path!r}\n"
                    "  This is often caused by antivirus software quarantining the file.\n"
                    "  Check your antivirus exclusions for: " + sb_drivers_dir
                )
        else:
            _log(f"chromedriver found at {chromedriver_path!r}")

        # Copy chromedriver to uc_driver if needed
        if os.path.exists(chromedriver_path) and not os.path.exists(uc_driver_path):
            shutil.copy2(chromedriver_path, uc_driver_path)

        # SeleniumBase's undetected mode expects to find both "uc_driver" and "undetected_chromedriver"
        # They should be identical copies of chromedriver (the UC patcher will modify them)
        undetected_path = os.path.join(sb_drivers_dir, undetected_name)
        if os.path.exists(uc_driver_path):
            temp_patcher = patcher.Patcher(executable_path=uc_driver_path)
            if not temp_patcher.is_binary_patched():
                temp_patcher.patch_exe()

            if not os.path.exists(undetected_path):
                shutil.copy2(uc_driver_path, undetected_path)

        Driver = importlib.import_module("seleniumbase.plugins.driver_manager").Driver  # pylint: disable=invalid-name

        flatpak_chrome = _find_flatpak_chrome()
        if flatpak_chrome:
            _log(f"Flatpak Chrome detected: {flatpak_chrome!r}")
        elif os.environ.get("FLATPAK_ID"):
            _log(
                "Running inside a flatpak but no Chrome/Chromium flatpak binary found. "
                "If Chrome is installed as a flatpak, run: "
                "flatpak override --user com.calibre_ebook.calibre --filesystem=host"
            )

        driver = None
        try:
            chrome_args = [
                f"--user-data-dir={user_data_dir}",
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
            ]

            # Chrome cannot create its own kernel sandbox inside an existing
            # sandbox (e.g. a flatpak bubblewrap container), so --no-sandbox
            # is required.  Only add it when we know we're in a flatpak.
            if os.environ.get("FLATPAK_ID"):
                chrome_args.append("--no-sandbox")

            # In CI, keep window maximized and visible
            # On local machines, move window far off-screen to hide it
            if os.environ.get("CI"):
                chrome_args.append("--start-maximized")
            else:
                chrome_args.append("--window-position=-32000,-32000")

            driver = Driver(
                uc=True,
                headless=False,
                chromium_arg=chrome_args,
                binary_location=flatpak_chrome,
            )

            try:
                _chrome_ver = driver.capabilities.get("browserVersion") or driver.capabilities.get("version", "unknown")
                _driver_ver = (driver.capabilities.get("chrome", {}) or {}).get("chromedriverVersion", "unknown")
                if isinstance(_driver_ver, str):
                    _driver_ver = _driver_ver.split(" ")[0]  # strip trailing platform info
                _log(f"Chrome version: {_chrome_ver}, chromedriver version: {_driver_ver}")
            except Exception:  # pylint: disable=broad-except
                pass

            time.sleep(random.uniform(0.2, 0.5))

            # Navigate to URL
            driver.get(url)

            time.sleep(random.uniform(0.5, 1.0))

            start_time = time.time()
            cleared = False
            cloudflare_indicators = [
                "Just a moment",
                "Checking your browser",
                "Verifying you are human",
            ]

            while time.time() - start_time < max_wait:
                try:
                    page_source = driver.page_source

                    # If page source is empty or very small, wait for it to load
                    if not page_source or len(page_source) < 100:
                        size = len(page_source) if page_source else 0
                        _log(f"Page source too small ({size} bytes), waiting...")
                        time.sleep(1)
                        continue

                    # Check for CloudFlare challenge indicators (case-insensitive)
                    page_lower = page_source.lower()
                    has_cloudflare = any(indicator.lower() in page_lower for indicator in cloudflare_indicators)

                    if has_cloudflare:
                        matched = [ind for ind in cloudflare_indicators if ind.lower() in page_lower]
                        _log(f"CloudFlare challenge detected (matched: {matched}), waiting...")
                        time.sleep(1)
                        continue

                    # Page loaded successfully
                    _log(f"Page loaded successfully ({len(page_source)} bytes)")
                    cleared = True
                    break

                except Exception as e:  # pylint: disable=broad-except
                    _log(f"Error checking page: {e}")
                    time.sleep(1)

            if not cleared:
                _log("Timeout waiting for Cloudflare")
                return None

            # Now wait for the actual content to load
            if wait_for_element:
                remaining_time = max(10, max_wait - (time.time() - start_time))
                element_start = time.time()

                while time.time() - element_start < remaining_time:
                    page_source = driver.page_source
                    if wait_for_element in page_source:
                        if secondary_wait_element:
                            # Container found; now wait for JS-rendered content within
                            # remaining time. Return the page whether or not it appears
                            # (genuine 0-result pages will never have it).
                            secondary_start = time.time()
                            secondary_remaining = remaining_time - (secondary_start - element_start)
                            while time.time() - secondary_start < secondary_remaining:
                                page_source = driver.page_source
                                if secondary_wait_element in page_source:
                                    _log(f"Secondary element '{secondary_wait_element}' found")
                                    return page_source
                                time.sleep(0.5)
                            _log(f"Secondary element '{secondary_wait_element}' not found (page may have 0 results)")
                            return driver.page_source
                        # Element found - give JS a brief moment to finish any remaining rendering.
                        time.sleep(1.0)
                        page_source = driver.page_source
                        return page_source
                    # Early exit: if the not_found_marker is present and the primary element
                    # still isn't, the page will never satisfy wait_for_element (e.g. a 404
                    # error page that will never contain book-stats). Return immediately.
                    if not_found_marker and not_found_marker.lower() in page_source.lower():
                        _log("Not-found marker detected, returning page early")
                        return page_source
                    time.sleep(0.5)

                _log(f"Timeout waiting for element: {wait_for_element}")
                return None
            return driver.page_source

        except Exception as e:  # pylint: disable=broad-except
            msg = str(e)
            # Check for seleniumbase ImportError first - non-retryable, propagate immediately
            if "seleniumbase" in msg.lower() and type(e).__name__ in ("ImportError", "ModuleNotFoundError"):
                raise SeleniumBaseImportError(
                    f"SeleniumBase (bundled browser automation) could not be loaded: {e}\n"
                    "This usually means the plugin zip's vendored packages aren't accessible\n"
                    "in the current process. Try reinstalling the plugin or restarting Calibre."
                ) from e
            if "chrome not found" in msg.lower() or "install it first" in msg.lower():
                raise ChromeNotInstalledError(msg) from e
            if "rosetta" in msg.lower():
                raise RosettaNotInstalledError(
                    "Your Mac is missing a required compatibility layer (Rosetta 2) needed to run the web browser automation."
                ) from e
            if "session not created" in msg.lower() or "this version of chromedriver only supports" in msg.lower():
                _log(
                    f"Chrome version mismatch: {e}\n"
                    "  The downloaded chromedriver doesn't match your installed Chrome version.\n"
                    f"  Delete the drivers folder and retry: {sb_drivers_dir}"
                )
                return None
            _log(f"Chrome error: {type(e).__name__}: {e}")
            import traceback

            _log(traceback.format_exc())
            return None
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as quit_err:  # pylint: disable=broad-except
                    _log(f"Error closing driver: {quit_err}")
            # Always remove the throw-away Chrome profile dir created above.
            if user_data_dir and os.path.isdir(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                except Exception:  # pylint: disable=broad-except
                    pass  # best effort - temp dir cleanup is non-critical
    except ChromeNotInstalledError:
        raise  # propagate immediately - no point retrying
    except RosettaNotInstalledError:
        raise  # propagate immediately - no point retrying
    except SeleniumBaseImportError:
        raise  # propagate immediately - no point retrying
    except Exception as e:  # pylint: disable=broad-except
        # Use type name as fallback in case isinstance fails due to class identity issues
        # (can happen when the same module is loaded under two different names in sys.modules)
        is_import_error = isinstance(e, ImportError) or type(e).__name__ in ("ImportError", "ModuleNotFoundError")
        if is_import_error and "seleniumbase" in str(e).lower():
            import traceback as _tb
            import zipfile as _zf

            # Log the full chained traceback through calibre's job log (not just stderr).
            _log(_tb.format_exc())
            # Log sys.path so we can see whether the plugin zip is on it.
            _plugin_entries = [p for p in sys.path if "calibre" in p.lower() or p.endswith(".zip")]
            _log(f"sys.path (calibre/zip entries): {_plugin_entries}")
            # Verify the zip contains the seleniumbase files we need.
            _zip_path = os.path.dirname(os.path.abspath(__file__))
            if os.path.isfile(_zip_path) and _zf.is_zipfile(_zip_path):
                with _zf.ZipFile(_zip_path) as _zf_obj:
                    _sb_files = [n for n in _zf_obj.namelist() if n.startswith("seleniumbase/")]
                    _log(f"Zip contains {len(_sb_files)} seleniumbase/* files")
                    _missing = [
                        f
                        for f in ["seleniumbase/__init__.py", "seleniumbase/core/browser_launcher.py"]
                        if f not in _sb_files
                    ]
                    if _missing:
                        _log(f"WARNING: missing from zip: {_missing}")
            else:
                _log(f"Vendored path is a directory (not a zip): {_zip_path!r}")
            # Include the root cause in the error message.
            root_cause = e.__cause__ or e
            root_msg = f"{type(root_cause).__name__}: {root_cause}" if root_cause is not e else ""
            detail = f"\n  Root cause: {root_msg}" if root_msg else ""
            raise SeleniumBaseImportError(
                f"SeleniumBase (bundled browser automation) could not be loaded: {e}{detail}\n"
                "This usually means the plugin zip's vendored packages aren't accessible\n"
                "in the current process. Try reinstalling the plugin or restarting Calibre."
            ) from e
        _log(f"Top-level error in fetch_page: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return None
    finally:
        # Catch-all cleanup: if setup code threw before reaching the inner try/finally,
        # user_data_dir would not have been cleaned up there. Clean it up here.
        if user_data_dir and os.path.isdir(user_data_dir):
            shutil.rmtree(user_data_dir, ignore_errors=True)


def fetch_romanceio_book_page(url, plugin_name, log=None):
    """
    Fetch a Romance.io book page with validation.

    Args:
        url: Romance.io book URL to fetch
        plugin_name: Name of the plugin ('romanceio' or 'romanceio_fields') for imports
        log: Optional logger for messages

    Returns:
        Tuple of (page_html, is_valid):
            - page_html: HTML string or None on error
            - is_valid: True if valid book page, False if 404/invalid
    """

    def log_msg(msg):
        if log:
            if hasattr(log, "info"):
                log.info(msg)
            else:
                log(msg)
        else:
            print(msg)

    def log_error(msg):
        if log:
            if hasattr(log, "error"):
                log.error(msg)
            else:
                log(msg)
        else:
            print(msg)

    # Single fetch: wait for book-stats to render, but exit immediately if a
    # 404/not-found page is detected so we don't burn the full timeout.
    _not_found_text = "the page you are looking for can't be found"
    page_html = fetch_page(
        url,
        plugin_name,
        wait_for_element="book-stats",
        not_found_marker=_not_found_text,
        max_wait=60,
        log_func=log_msg,
    )

    if not page_html:
        log_error("Failed to fetch page (Chrome timed out or crashed - check terminal for details)")
        return None, False

    if _not_found_text in page_html.lower():
        log_error(f"Invalid Romance.io ID (404): {url}")
        return page_html, False

    if "book-stats" not in page_html:
        log_error(f"Page missing book-stats element after waiting: {url}")
        return page_html, False

    return page_html, True
