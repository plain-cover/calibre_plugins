"""
Shared helper for fetching pages with SeleniumBase.
Used by both romanceio and romanceio_fields plugins.
"""

import importlib
import importlib.abc
import os
import platform
import random
import shutil
import sys
import tempfile
import time
import types
from typing import Optional, Sequence

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

    def __init__(self, plugin_name, packages=None):
        self.plugin_name = plugin_name
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
            # Our own re-entrancy placeholder — return to prevent infinite recursion
            return existing
        if existing is not None and getattr(existing, "__file__", None) is not None:
            # Fully-loaded module (has __file__) — safe to reuse
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
        except Exception:
            sys.modules.pop(fullname, None)
            sys.modules.pop(real_name, None)
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
            except Exception:
                raise ImportError(f"No module named {fullname!r}")
            finally:
                if was_in:
                    sys.meta_path.insert(0, self)  # type: ignore[arg-type]


def fetch_page(url, plugin_name, wait_for_element=None, max_wait=30, log_func=None):
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
        max_wait: Maximum seconds to wait for page load
        log_func: Optional logging function to route errors to calibre's job log

    Returns:
        Page HTML as string, or None on error
    """

    def _log(msg):
        print(msg)
        if log_func:
            log_func(msg)

    try:
        # Use a stable driver directory under the user's home dir so chromedriver
        # persists across calibre sessions (calibre rotates its own temp dir each run)
        stable_base = os.path.join(os.path.expanduser("~"), ".calibre_selenium")
        sb_drivers_dir = os.path.abspath(os.path.join(stable_base, "drivers"))
        downloads_dir = os.path.abspath(os.path.join(stable_base, "downloads"))
        # Use unique user_data_dir for each Chrome instance to prevent locking issues
        # when multiple instances run simultaneously (e.g., search + worker threads)
        user_data_dir = os.path.abspath(os.path.join(stable_base, "user_data", f"profile_{os.getpid()}_{time.time()}"))

        # Ensure all directories exist with proper permissions
        for dir_path in [sb_drivers_dir, downloads_dir, user_data_dir]:
            os.makedirs(dir_path, exist_ok=True)

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
            finder: VendoredPackageFinder = VendoredPackageFinder(plugin_name)  # type: ignore[assignment]
            sys.meta_path.insert(0, finder)  # type: ignore[arg-type]

        # Add the plugin's package directory to sys.path so vendored packages
        # can be imported directly via zipimport. This is required in calibre GUI
        # mode where the plugin is loaded from a zip that isn't on sys.path.
        #
        # Key insight: vendored packages (seleniumbase/, selenium/, …) sit ALONGSIDE
        # the plugin's __init__.py, so the correct sys.path entry is the plugin's
        # own package directory — not the zip root:
        #   __file__  = 'Romance.io.zip/romanceio/__init__.py'
        #   dirname   = 'Romance.io.zip/romanceio'   ← add this
        #   zip root  = 'Romance.io.zip'             ← WRONG (seleniumbase not at top level)
        #
        # Calibre sometimes also sets __path__ to the bare zip root; we detect that
        # and append plugin_name to reconstruct the correct subpath.
        plugin_module = sys.modules.get(f"calibre_plugins.{plugin_name}")
        if plugin_module:
            plugin_sys_path = None
            # dirname(__file__) gives the package dir for both real and zip paths
            plugin_file = getattr(plugin_module, "__file__", None)
            if plugin_file:
                plugin_sys_path = os.path.dirname(os.path.normpath(str(plugin_file)))
            # Fall back to __path__
            if not plugin_sys_path:
                for p in getattr(plugin_module, "__path__", None) or []:
                    p_norm = os.path.normpath(str(p))
                    if p_norm.lower().endswith(".zip") and os.path.isfile(p_norm):
                        # Calibre set __path__ to the zip root; plugin dir is one level deeper
                        plugin_sys_path = os.path.join(p_norm, plugin_name)
                    elif p_norm:
                        plugin_sys_path = p_norm
                    if plugin_sys_path:
                        break
            if plugin_sys_path and plugin_sys_path not in sys.path:
                sys.path.insert(0, plugin_sys_path)

        # Import and patch constants FIRST to avoid Windows permission errors.
        # Use bare module names (e.g. "seleniumbase.fixtures.constants") rather than
        # "calibre_plugins.{plugin_name}.seleniumbase.fixtures.constants".  In calibre
        # GUI mode the plugin is loaded from a zip and Python's FileFinder tries to
        # open 'Romance.io.zip\seleniumbase' as a real directory, causing
        # FileNotFoundError.  Bare-name imports go through VendoredPackageFinder which
        # redirects to the plugin namespace and falls back to zipimport on failure.
        constants = importlib.import_module("seleniumbase.fixtures.constants")

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
            sb_install.main("chromedriver latest")

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
            )

            time.sleep(random.uniform(0.5, 1.5))

            # Navigate to URL
            driver.get(url)

            time.sleep(random.uniform(1, 2))

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
                remaining_time = max_wait - (time.time() - start_time)
                element_start = time.time()

                while time.time() - element_start < remaining_time:
                    page_source = driver.page_source
                    if wait_for_element in page_source:
                        # Give JavaScript a moment to finish rendering
                        time.sleep(1)
                        page_source = driver.page_source
                        return page_source
                    time.sleep(0.5)

                _log(f"Timeout waiting for element: {wait_for_element}")
                return None
            return driver.page_source

        except Exception as e:  # pylint: disable=broad-except
            _log(f"Chrome error: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
            return None
        finally:
            if driver:
                try:
                    driver.quit()
                    time.sleep(0.5)  # Give Chrome time to close
                except Exception as quit_err:  # pylint: disable=broad-except
                    _log(f"Error closing driver: {quit_err}")
    except Exception as e:  # pylint: disable=broad-except
        _log(f"Top-level error in fetch_page: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return None


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

    # First fetch without waiting for specific element to check for 404
    page_html = fetch_page(url, plugin_name, wait_for_element=None, max_wait=60, log_func=log_msg)

    if not page_html:
        log_error("Failed to fetch page (Chrome timed out or crashed - check terminal for details)")
        return None, False

    if "the page you are looking for can't be found" in page_html.lower():
        log_error(f"Invalid Romance.io ID (404): {url}")
        return page_html, False

    # Valid page - check if book-stats is present
    if "book-stats" not in page_html:
        log_msg("book-stats not found on first load, waiting for it to render...")
        # Retry with explicit wait for book-stats element
        page_html = fetch_page(url, plugin_name, wait_for_element="book-stats", max_wait=30, log_func=log_msg)

        if not page_html:
            log_error("Failed to fetch page on retry (Chrome timed out or crashed - check terminal for details)")
            return None, False

        if "book-stats" not in page_html:
            log_error(f"Page missing book-stats element after retry: {url}")
            return page_html, False

        log_msg("book-stats found after waiting")

    return page_html, True
