"""
Shared HTTP fetching and supervised embedded-browser lifecycle.
Selenium provides an optional last resort after the embedded engine fails.
Used by both romanceio and romanceio_fields plugins.
"""

import glob
import hashlib
import importlib
import importlib.abc
import json
from importlib import metadata as importlib_metadata
import os
import platform
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import zipfile
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import urljoin, urlparse

# List of vendored packages that need import redirection
VENDORED_PACKAGES = [
    "attr",
    "attrs",
    "certifi",
    "charset_normalizer",
    "colorama",
    "cssselect",
    "exceptiongroup",
    "fake_useragent",
    "fasteners",
    "filelock",
    "h11",
    "idna",
    "mycdp",
    "outcome",
    "packaging",
    "platformdirs",
    "requests",
    "sbvirtualdisplay",
    "selenium",
    "seleniumbase",
    "six",
    "sniffio",
    "socks",
    "sortedcontainers",
    "trio",
    "trio_websocket",
    "typing_extensions",
    "urllib3",
    "websocket",
    "websocket_client",
    "websockets",
    "wsproto",
]

_BROWSER_IMPORT_STATE_MODULE = "_calibre_romanceio_browser_import_state"


def _new_browser_import_state() -> types.ModuleType:
    """Create process-wide state shared by both installed Romance.io plugins."""
    state = types.ModuleType(_BROWSER_IMPORT_STATE_MODULE)
    state.import_lock = threading.RLock()  # type: ignore[attr-defined]
    return state


# This helper is copied into two separately-namespaced plugin ZIPs. A normal
# module global would therefore create one lock per plugin even though both
# copies mutate the same process-wide import tables. sys.modules is shared by
# the whole Calibre interpreter, so it provides a stable rendezvous point.
_BROWSER_IMPORT_STATE = sys.modules.setdefault(
    _BROWSER_IMPORT_STATE_MODULE,
    _new_browser_import_state(),
)
_BROWSER_IMPORT_LOCK = _BROWSER_IMPORT_STATE.import_lock  # type: ignore[attr-defined]

_ALLOWED_DRIVER_DOWNLOAD_HOSTS = frozenset(
    {
        "chromedriver.storage.googleapis.com",
        "googlechromelabs.github.io",
        "storage.googleapis.com",
    }
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_EXECUTABLE_VERSION_PATTERN = re.compile(
    r"\b(?:chromedriver|chrome|chromium)(?:\s+(?:for\s+testing|beta|dev|canary))?\s+(\d+)",
    re.IGNORECASE,
)
_DRIVER_CACHE_LOCK_TIMEOUT_SECONDS = 120
_MAX_DRIVER_DOWNLOAD_REDIRECTS = 30


def validate_driver_download_url(url: str) -> str:
    """Reject non-TLS or non-Google origins used during ChromeDriver setup."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"Refusing non-HTTPS ChromeDriver download URL: {url}")
    if hostname not in _ALLOWED_DRIVER_DOWNLOAD_HOSTS:
        raise RuntimeError(f"Refusing unapproved ChromeDriver download host {hostname!r}: {url}")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise RuntimeError(f"Refusing unusual ChromeDriver download URL: {url}")
    return url


def _secure_seleniumbase_request(sb_install: Any, url: str, timeouts: Sequence[float]) -> Any:
    """Perform SeleniumBase's metadata/artifact request without HTTP downgrade."""
    validate_driver_download_url(url)
    use_proxy, protocol, proxy_string = sb_install.get_proxy_info()
    proxies = {protocol: proxy_string} if use_proxy else None
    last_error = None
    for timeout in timeouts:
        try:
            request_url = url
            for redirect_count in range(_MAX_DRIVER_DOWNLOAD_REDIRECTS + 1):
                response = sb_install.requests.get(request_url, proxies=proxies, timeout=timeout, allow_redirects=False)
                keep_response = False
                try:
                    response_url = validate_driver_download_url(getattr(response, "url", request_url))
                    response.raise_for_status()
                    if response.status_code not in (301, 302, 303, 307, 308):
                        keep_response = True
                        return response
                    if redirect_count == _MAX_DRIVER_DOWNLOAD_REDIRECTS:
                        raise RuntimeError("Too many ChromeDriver download redirects")
                    location = response.headers.get("Location")
                    if not location:
                        raise RuntimeError("ChromeDriver download redirect has no Location header")
                    # Validate before sending the next request, including relative
                    # and scheme-relative redirects. Checking only the final URL
                    # would allow an intermediate HTTP or unapproved-host hop.
                    request_url = validate_driver_download_url(urljoin(response_url, location))
                finally:
                    if not keep_response:
                        response.close()
        except Exception as error:  # pylint: disable=broad-except
            last_error = error
    raise RuntimeError(f"Secure ChromeDriver request failed for {url}: {last_error}") from last_error


def configure_secure_driver_downloads(sb_install: Any) -> None:
    """Replace SeleniumBase download helpers with strict HTTPS/host validation."""
    sb_install.requests_get = lambda url: _secure_seleniumbase_request(sb_install, url, (1.25, 2.75))
    sb_install.requests_get_with_retry = lambda url: _secure_seleniumbase_request(
        sb_install,
        url,
        (1.35, 2.45, 3.55),
    )


def _sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_driver_integrity(path: str) -> str:
    """Atomically record a checksum for later corruption/race detection.

    The adjacent checksum is not an independent provenance or authenticity
    guarantee: a process that can replace the driver can usually replace the
    checksum too. Download provenance is instead constrained by
    ``validate_driver_download_url()``.
    """
    digest = _sha256_file(path)
    record_path = path + ".sha256"
    record_directory = os.path.dirname(os.path.abspath(record_path))
    descriptor, temporary_record = tempfile.mkstemp(
        prefix=os.path.basename(record_path) + ".",
        suffix=".tmp",
        dir=record_directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as record:
            record.write(digest + "\n")
        os.replace(temporary_record, record_path)
    finally:
        if os.path.exists(temporary_record):
            os.remove(temporary_record)
    return digest


def verify_driver_integrity(path: str) -> Optional[str]:
    """Check ChromeDriver against its local baseline, if one is available."""
    record_path = path + ".sha256"
    if not os.path.exists(record_path):
        return None
    try:
        with open(record_path, "r", encoding="ascii") as record:
            expected = record.read().strip().lower()
    except UnicodeDecodeError as error:
        raise RuntimeError(f"ChromeDriver integrity record is malformed: {record_path}") from error
    if not _SHA256_PATTERN.fullmatch(expected):
        raise RuntimeError(f"ChromeDriver integrity record is malformed: {record_path}")
    actual = _sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"ChromeDriver integrity check failed for {path}.")
    return actual


def _executable_major_version(path: str) -> Optional[int]:
    """Return a Chrome-family executable's major version, if it can run."""
    try:
        completed = subprocess.run(
            [path, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # Calibre workers have no console to inherit. Without this flag,
            # Windows briefly creates one for each ChromeDriver version probe.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
            timeout=5,
            universal_newlines=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    match = _EXECUTABLE_VERSION_PATTERN.search(completed.stdout or "")
    return int(match.group(1)) if match else None


def _remove_driver_cache_entry(path: str) -> None:
    """Remove a managed driver and its adjacent local checksum."""
    for cache_path in (path, path + ".sha256"):
        try:
            os.remove(cache_path)
        except FileNotFoundError:
            pass


def prepare_cached_chromedriver(
    sb_install: Any,
    interprocess_lock_class: Any,
    stable_base: str,
    chromedriver_path: str,
    runtime_chromedriver_path: str,
    log_func: Callable[[str], None],
    browser_major_version: Optional[int] = None,
) -> str:
    """Install/check/copy ChromeDriver while serializing the shared cache.

    Installed plugin calls run in separate Calibre worker processes. A
    ``threading.RLock`` cannot protect the persistent cache across those
    processes, so all cache inspection and mutation happens under SeleniumBase's
    cross-platform ``fasteners.InterProcessLock`` implementation.
    """
    lock_path = os.path.abspath(os.path.join(stable_base, "chromedriver-install.lock"))
    cache_lock = interprocess_lock_class(lock_path)
    acquired = cache_lock.acquire(blocking=True, timeout=_DRIVER_CACHE_LOCK_TIMEOUT_SECONDS)
    if not acquired:
        raise RuntimeError("Timed out waiting for another Calibre job to finish preparing ChromeDriver")

    digest: Optional[str] = None
    try:
        install_reason: Optional[str] = None
        if os.path.exists(chromedriver_path):
            try:
                digest = verify_driver_integrity(chromedriver_path)
            except (OSError, RuntimeError) as error:
                log_func(
                    "chromedriver cache failed its local integrity check; "
                    f"removing it and downloading a clean copy: {error}"
                )
                _remove_driver_cache_entry(chromedriver_path)
                install_reason = "cache recovery"
            else:
                if digest is None:
                    # Preserve upgrades for users with a driver installed by an older
                    # plugin version. This baseline detects later corruption and cache
                    # races; it does not retroactively establish download provenance.
                    digest = record_driver_integrity(chromedriver_path)
                    log_func(
                        "chromedriver found; recorded a local SHA-256 baseline for the legacy cache "
                        f"(corruption detection only): {digest}"
                    )
                else:
                    log_func(f"chromedriver checksum verified (SHA-256: {digest})")

                if browser_major_version is not None:
                    driver_major_version = _executable_major_version(chromedriver_path)
                    if driver_major_version is None:
                        log_func(
                            "cached chromedriver cannot execute or report its version; " "refreshing the shared cache"
                        )
                        _remove_driver_cache_entry(chromedriver_path)
                        digest = None
                        install_reason = "unusable cached executable"
                    elif driver_major_version != browser_major_version:
                        log_func(
                            f"cached chromedriver {driver_major_version} does not match "
                            f"installed Chrome {browser_major_version}; refreshing the shared cache"
                        )
                        _remove_driver_cache_entry(chromedriver_path)
                        digest = None
                        install_reason = "Chrome version change"
        else:
            install_reason = "first use"

        if install_reason is not None:
            requested_version = str(browser_major_version) if browser_major_version is not None else "latest"
            log_func(
                "chromedriver is not usable in the managed driver directory; "
                f"downloading version {requested_version} ({install_reason})..."
            )
            sb_install.main(f"chromedriver {requested_version}")
            if not os.path.exists(chromedriver_path):
                raise RuntimeError(
                    "chromedriver download failed - file missing after install attempt.\n"
                    "  This is often caused by antivirus software quarantining the file.\n"
                    "  Check your antivirus quarantine and the managed Calibre Selenium directory."
                )
            if browser_major_version is not None:
                downloaded_major_version = _executable_major_version(chromedriver_path)
                if downloaded_major_version != browser_major_version:
                    _remove_driver_cache_entry(chromedriver_path)
                    reported_version = (
                        "could not execute" if downloaded_major_version is None else str(downloaded_major_version)
                    )
                    raise RuntimeError(
                        "Downloaded ChromeDriver is unusable for the installed browser: "
                        f"expected major {browser_major_version}, driver {reported_version}."
                    )
            digest = record_driver_integrity(chromedriver_path)
            log_func(f"chromedriver downloaded successfully (SHA-256 baseline: {digest})")

        cached_driver_digest = verify_driver_integrity(chromedriver_path)
        if cached_driver_digest is None:
            raise RuntimeError("Managed chromedriver has no checksum record")

        shutil.copy2(chromedriver_path, runtime_chromedriver_path)
        if _sha256_file(runtime_chromedriver_path) != cached_driver_digest:
            raise RuntimeError("chromedriver changed while creating the private worker copy")
    finally:
        cache_lock.release()

    record_driver_integrity(runtime_chromedriver_path)
    verify_driver_integrity(runtime_chromedriver_path)
    return cached_driver_digest


def prepare_uc_driver(chromedriver_path: str, uc_driver_path: str, patcher_class: Any) -> str:
    """Rebuild and verify the exact UC executable that SeleniumBase will launch.

    ``chromedriver`` is the locally checksummed source. The patched UC
    binary is created at a random sibling path and atomically replaces any stale
    or locally modified copy. Installed-plugin callers use a per-worker directory,
    so concurrent Calibre jobs never share the executable being launched.
    """
    source_digest = verify_driver_integrity(chromedriver_path)
    if source_digest is None:
        raise RuntimeError("Refusing to build uc_driver from an unverified chromedriver")

    driver_directory = os.path.dirname(os.path.abspath(uc_driver_path))
    temporary_suffix = ".tmp.exe" if uc_driver_path.lower().endswith(".exe") else ".tmp"
    descriptor, temporary_driver = tempfile.mkstemp(
        prefix=os.path.basename(uc_driver_path) + ".",
        suffix=temporary_suffix,
        dir=driver_directory,
    )
    os.close(descriptor)
    try:
        shutil.copy2(chromedriver_path, temporary_driver)
        if _sha256_file(temporary_driver) != source_digest:
            raise RuntimeError("chromedriver changed while preparing the UC executable")
        uc_patcher = patcher_class(executable_path=temporary_driver)
        if not uc_patcher.is_binary_patched():
            uc_patcher.patch_exe()
        os.replace(temporary_driver, uc_driver_path)
        digest = record_driver_integrity(uc_driver_path)
        if verify_driver_integrity(uc_driver_path) != digest:
            raise RuntimeError("uc_driver integrity verification failed after installation")
        return digest
    finally:
        if os.path.exists(temporary_driver):
            os.remove(temporary_driver)


def _redact_log_text(message: Any) -> str:
    """Hide user-home and temporary-directory prefixes from shareable job logs."""
    redacted = str(message)
    replacements = (
        (os.path.abspath(tempfile.gettempdir()), "<temp>"),
        (os.path.abspath(os.path.expanduser("~")), "~"),
    )
    for path, label in replacements:
        windows_path = path.replace("/", "\\")
        posix_path = path.replace("\\", "/")
        variants = {
            path,
            windows_path,
            posix_path,
            windows_path.replace("\\", "\\\\"),
            posix_path.replace("/", "//"),
        }
        for variant in sorted(variants, key=len, reverse=True):
            if variant:
                redacted = re.sub(re.escape(variant), label, redacted, flags=re.IGNORECASE)
    return redacted


def browser_vendor_branch(version_info: Optional[Sequence[int]] = None) -> str:
    """Return SeleniumBase's dependency branch for a Python runtime."""
    version = version_info or sys.version_info
    major_minor = tuple(version[:2])
    if major_minor < (3, 8):
        raise RuntimeError(f"Python 3.8 or newer is required, found {major_minor!r}")
    if major_minor == (3, 8):
        return "py38"
    if major_minor == (3, 9):
        return "py39"
    return "current"


def _browser_vendor_source_is_valid(path: str, plugin_name: str) -> bool:
    """Return whether *path* is this plugin's directory or installed ZIP."""
    marker = f"plugin-import-name-{plugin_name}.txt"
    seleniumbase_init = "browser_vendor/shared/seleniumbase/__init__.py"
    try:
        if os.path.isdir(path):
            return os.path.isfile(os.path.join(path, marker)) and os.path.isfile(
                os.path.join(path, *seleniumbase_init.split("/"))
            )
        if os.path.isfile(path) and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as plugin_zip:
                names = set(plugin_zip.namelist())
            return marker in names and seleniumbase_init in names
    except (OSError, zipfile.BadZipFile):
        return False
    return False


def _filesystem_source_candidates(path: Any) -> List[str]:
    """Return real directory/ZIP candidates represented by a possibly virtual path."""
    try:
        candidate = os.path.abspath(os.fsdecode(os.fspath(path)))
    except (TypeError, ValueError):
        return []

    candidates = []
    # Calibre 5 reports ``<calibre Plugin Loader>`` as __file__, while newer
    # Calibre versions can report a virtual ``Plugin.zip/module.py`` path. Walk
    # upward so both real directories and the archive portion are considered.
    while candidate:
        candidates.append(candidate)
        parent = os.path.dirname(candidate.rstrip("/\\"))
        if not parent or parent == candidate:
            break
        candidate = parent
    return candidates


def _loader_source_candidates(loader: Any, plugin_name: str) -> List[Any]:
    """Read plugin paths exposed by current and legacy Calibre loaders."""
    if loader is None:
        return []

    candidates = []
    for attribute in ("zip_file_path", "plugin_path", "archive_path"):
        try:
            value = getattr(loader, attribute, None)
        except Exception:  # pylint: disable=broad-except
            continue
        if value:
            candidates.append(value)

    # Calibre 5's shared PluginLoader sets module.__file__ to a placeholder,
    # but retains ``plugin_name: (zip_path, module_names)`` in this mapping.
    try:
        loaded_plugins = getattr(loader, "loaded_plugins", None)
    except Exception:  # pylint: disable=broad-except
        loaded_plugins = None
    if loaded_plugins is not None:
        try:
            entry = loaded_plugins.get(plugin_name)
        except (AttributeError, TypeError):
            entry = None
        if isinstance(entry, (tuple, list)) and entry:
            candidates.append(entry[0])
        elif isinstance(entry, dict):
            for key in ("zip_file_path", "plugin_path", "archive_path", "path"):
                if entry.get(key):
                    candidates.append(entry[key])
    return candidates


def resolve_browser_vendor_source(
    plugin_name: str,
    module_file: Optional[str] = None,
    module_loader: Any = None,
    search_path: Optional[Sequence[str]] = None,
    meta_path: Optional[Sequence[Any]] = None,
) -> str:
    """Locate the plugin directory or ZIP that owns the browser dependencies.

    Calibre 5 uses ``<calibre Plugin Loader>`` for plugin module ``__file__``
    values. Its loader mapping is therefore authoritative and must be checked
    before the current working directory implied by that placeholder.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", plugin_name):
        raise ValueError(f"Invalid plugin import name: {plugin_name!r}")

    if module_file is None:
        module_file = __file__
    if module_loader is None:
        module_loader = globals().get("__loader__")
    if search_path is None:
        search_path = sys.path
    if meta_path is None:
        meta_path = sys.meta_path

    raw_candidates = []
    raw_candidates.extend(_loader_source_candidates(module_loader, plugin_name))
    module_spec = globals().get("__spec__")
    raw_candidates.extend(_loader_source_candidates(getattr(module_spec, "loader", None), plugin_name))
    zipplugin_module = sys.modules.get("calibre.customize.zipplugin")
    raw_candidates.extend(_loader_source_candidates(getattr(zipplugin_module, "loader", None), plugin_name))
    for finder in meta_path:
        raw_candidates.extend(_loader_source_candidates(finder, plugin_name))

    # Loader-owned paths come first. This prevents a Calibre 5 placeholder
    # __file__ from accidentally selecting a checkout in the launch directory.
    raw_candidates.append(module_file)
    raw_candidates.extend(search_path)
    module_parent = os.path.dirname(os.path.dirname(os.path.abspath(module_file)))
    raw_candidates.append(os.path.join(module_parent, plugin_name))

    seen = set()
    for raw_candidate in raw_candidates:
        for candidate in _filesystem_source_candidates(raw_candidate):
            normalized = os.path.normcase(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            if _browser_vendor_source_is_valid(candidate, plugin_name):
                return candidate

    # Preserve the prior error path so callers receive the existing actionable
    # SeleniumBaseImportError if an installation is incomplete or corrupted.
    return os.path.dirname(os.path.abspath(module_file))


def configure_browser_vendor_path(
    plugin_dir: str,
    version_info: Optional[Sequence[int]] = None,
) -> List[str]:
    """Put the matching runtime branch and shared browser packages on sys.path."""
    vendor_root = plugin_dir.rstrip("/\\") + "/browser_vendor"
    shared_path = vendor_root + "/shared"
    branch_path = vendor_root + "/" + browser_vendor_branch(version_info)

    # Insert shared first so the runtime-specific branch ends up at higher
    # priority and wins for dependencies present in both locations.
    for path in (shared_path, branch_path):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    return [branch_path, shared_path]


def _normalized_distribution_name(name: str) -> str:
    """Normalize a distribution name using the PyPA name-matching rules."""
    return re.sub(r"[-_.]+", "-", name).lower()


class BrowserVendorDistribution(importlib_metadata.Distribution):
    """Distribution metadata stored below a vendor root inside a plugin ZIP."""

    def __init__(self, archive_path: str, vendor_prefix: str, metadata_prefix: str, metadata_text: str):
        self.archive_path = archive_path
        self.vendor_prefix = vendor_prefix.rstrip("/") + "/"
        self.metadata_prefix = metadata_prefix.rstrip("/") + "/"
        self._texts: Dict[str, Optional[str]] = {"METADATA": metadata_text}

    def read_text(self, filename):
        if filename not in self._texts:
            try:
                with zipfile.ZipFile(self.archive_path) as plugin_zip:
                    self._texts[filename] = plugin_zip.read(self.metadata_prefix + filename).decode("utf-8")
            except (KeyError, OSError, UnicodeDecodeError):
                self._texts[filename] = None
        return self._texts[filename]

    def locate_file(self, path):
        relative = str(path).replace("\\", "/").lstrip("/")
        return zipfile.Path(self.archive_path, at=self.vendor_prefix + relative)


class BrowserVendorDistributionFinder(importlib.abc.MetaPathFinder):
    """Expose nested ZIP distribution metadata to importlib.metadata."""

    def __init__(self, archive_path: str, vendor_paths: Sequence[str]):
        self.archive_path = archive_path
        self.distributions = []
        self._by_name: Dict[str, List[BrowserVendorDistribution]] = {}
        with zipfile.ZipFile(archive_path) as plugin_zip:
            names = plugin_zip.namelist()
            for vendor_path in vendor_paths:
                vendor_prefix = vendor_path[len(archive_path) :].strip("/\\").replace("\\", "/")
                metadata_suffix = ".dist-info/METADATA"
                for name in names:
                    if not name.startswith(vendor_prefix + "/") or not name.endswith(metadata_suffix):
                        continue
                    relative = name[len(vendor_prefix) + 1 :]
                    if relative.count("/") != 1:
                        continue
                    distribution = BrowserVendorDistribution(
                        archive_path, vendor_prefix, name[: -len("METADATA")], plugin_zip.read(name).decode("utf-8")
                    )
                    self.distributions.append(distribution)
                    normalized_name = _normalized_distribution_name(distribution.metadata["Name"])
                    self._by_name.setdefault(normalized_name, []).append(distribution)

    def find_spec(self, fullname, path=None, target=None):  # pylint: disable=unused-argument
        return None

    def find_distributions(self, context=None):
        if context is None:
            context = importlib_metadata.DistributionFinder.Context()
        requested = _normalized_distribution_name(context.name) if context.name else None
        if requested is None:
            matches = self.distributions
        else:
            matches = self._by_name.get(requested, [])
        # Python 3.8's importlib.metadata calls next() directly on resolver
        # results, while newer versions accept any iterable.
        return iter(matches)


def configure_browser_vendor_metadata(
    plugin_dir: str,
    vendor_paths: Sequence[str],
) -> Optional[BrowserVendorDistributionFinder]:
    """Install nested-ZIP metadata discovery for the duration of a browser fetch."""
    if not os.path.isfile(plugin_dir) or not zipfile.is_zipfile(plugin_dir):
        return None
    finder = BrowserVendorDistributionFinder(plugin_dir, vendor_paths)
    sys.meta_path.insert(0, finder)
    return finder


def _browser_vendor_module_names(plugin_name: str) -> List[str]:
    """Return cached module names owned by the isolated browser stack."""
    browser_roots = set(VENDORED_PACKAGES)
    plugin_prefix = f"calibre_plugins.{plugin_name}."
    module_names = []
    for module_name in list(sys.modules):
        top_level = module_name.split(".", 1)[0]
        namespaced = module_name[len(plugin_prefix) :].split(".", 1)[0] if module_name.startswith(plugin_prefix) else ""
        if top_level in browser_roots or namespaced in browser_roots:
            module_names.append(module_name)
    return module_names


def snapshot_browser_vendor_modules(plugin_name: str) -> Dict[str, types.ModuleType]:
    """Capture browser modules that must be restored after an isolated fetch."""
    return {name: sys.modules[name] for name in _browser_vendor_module_names(plugin_name)}


def clear_browser_vendor_modules(plugin_name: str) -> None:
    """Remove cached browser modules so imports honor the selected vendor branch."""
    for module_name in _browser_vendor_module_names(plugin_name):
        sys.modules.pop(module_name, None)


def restore_browser_vendor_modules(plugin_name: str, snapshot: Dict[str, types.ModuleType]) -> None:
    """Remove the temporary browser stack and restore the host's prior modules."""
    clear_browser_vendor_modules(plugin_name)
    sys.modules.update(snapshot)


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

    def __init__(self, plugin_name, packages=None, plugin_dir=None, package_roots=None):
        self.plugin_name = plugin_name
        self.plugin_dir = plugin_dir
        self.package_roots = list(package_roots or ())
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
        if "." not in fullname:
            # zipimport expects 'zip_file_path/package_name' with forward slashes.
            # New release ZIPs keep packages below browser_vendor/<branch>;
            # plugin_dir remains supported for older/root-layout callers.
            roots = self.package_roots or ([self.plugin_dir] if self.plugin_dir else [])
            placeholder.__path__ = [root.rstrip("/\\") + "/" + fullname for root in roots]
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


class HttpAccessDeniedError(RuntimeError):
    """Plain HTTP was blocked; move to browser fallback without repeating it."""


class BrowserFetchError(RuntimeError):
    """A browser attempt failed or exhausted its budget; do not relaunch it."""


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


def _browser_binary_is_runnable(path: str) -> bool:
    """Return whether ``path`` is a directly executable Chrome-family binary."""
    return _executable_major_version(path) is not None


def browser_automation_unavailable_reason(
    system_name: Optional[str] = None,
    machine_name: Optional[str] = None,
) -> Optional[str]:
    """Explain platform combinations where the managed browser path cannot run."""
    system_name = system_name or platform.system()
    machine_name = (machine_name or platform.machine()).lower().replace("_", "-")
    is_arm = machine_name in ("aarch64", "arm64") or machine_name.startswith("arm")
    if system_name == "Linux" and is_arm:
        return (
            f"Chrome browser fallback is unavailable on Linux ARM ({machine_name}): "
            "Chrome for Testing does not publish a compatible Linux ARM ChromeDriver. "
            "JSON search and lightweight HTTP metadata remain available."
        )
    return None


def _installed_browser_major_version(detect_b_ver: Any, binary_location: Optional[str]) -> Optional[int]:
    """Best-effort detection used to keep the shared driver cache current."""
    if binary_location:
        return _executable_major_version(binary_location)
    try:
        version = detect_b_ver.get_browser_version_from_os("google-chrome")
    except Exception:  # pylint: disable=broad-except
        return None
    match = re.match(r"\s*(\d+)", str(version or ""))
    return int(match.group(1)) if match else None


def configure_macos_browser_detection(detect_b_ver: Any) -> None:
    """Read Chrome's bundle version without launching Chrome to probe it."""
    if sys.platform != "darwin":
        return
    original = detect_b_ver.get_browser_version_from_os

    def version_from_os(browser_type):
        if browser_type != "google-chrome":
            return original(browser_type)
        for directory in ("/Applications", os.path.expanduser("~/Applications")):
            path = os.path.join(directory, "Google Chrome.app", "Contents", "Info.plist")
            try:
                with open(path, "rb") as stream:
                    info = plistlib.load(stream)
                version = info.get("CFBundleShortVersionString", "") if isinstance(info, dict) else ""
                if isinstance(version, str) and re.fullmatch(r"\d+(?:\.\d+){2,3}", version):
                    return version
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
        return None

    # SeleniumBase calls this again while preparing the driver. Replace its
    # shared detector so that those calls also avoid unbounded shell probes.
    detect_b_ver.get_browser_version_from_os = version_from_os


def _find_flatpak_chrome() -> Optional[str]:
    """Return a directly runnable Chrome binary from Flatpak storage, if any.

    Flatpak app launchers such as ``org.chromium.Chromium/files/bin/chromium``
    depend on their own mounted ``/app`` runtime and cannot be passed to
    Selenium's ``binary_location`` from the host or from Calibre's different
    sandbox. Google Chrome's extra-data package may expose a direct binary on
    some installations, but it is returned only after an execution probe.
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
    ]
    for base in app_bases:
        for app_id, rel_path in candidates:
            # Use * for arch (e.g. x86_64) and branch (e.g. stable) levels
            pattern = os.path.join(base, app_id, "*", "*", "active", rel_path)
            for match in glob.glob(pattern):
                if os.access(match, os.X_OK) and _browser_binary_is_runnable(match):
                    return match
    return None


def _build_chrome_args(user_data_dir: str, inside_flatpak: bool, in_ci: bool) -> List[str]:
    """Build Chrome arguments without weakening the sandbox outside Flatpak."""
    chrome_args = [
        f"--user-data-dir={user_data_dir}",
        "--disable-blink-features=AutomationControlled",
        "--exclude-switches=enable-automation",
        "--disable-dev-shm-usage",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--disable-quic",
        "--disable-gpu",
        "--window-size=1920,1080",
    ]

    # Chrome cannot create its own kernel sandbox inside an existing Flatpak
    # bubblewrap sandbox. Never use this flag for ordinary desktop installs.
    if inside_flatpak:
        chrome_args.append("--no-sandbox")

    if in_ci:
        chrome_args.append("--start-maximized")
    else:
        chrome_args.append("--window-position=-32000,-32000")
    return chrome_args


class _LegacyUcSubprocessProxy:
    """Use current SeleniumBase's quiet browser/driver stdio on legacy branches."""

    def __init__(self, subprocess_module: Any):
        self._subprocess_module = subprocess_module

    def __getattr__(self, name: str) -> Any:
        # Legacy UC also passes subprocess.PIPE to Selenium's Service, which
        # launches ChromeDriver through a different module's Popen. Redirect
        # that handle at its source; intercepting UC's Popen alone misses it.
        if name == "PIPE":
            return self._subprocess_module.DEVNULL
        return getattr(self._subprocess_module, name)

    def Popen(self, *args: Any, **kwargs: Any) -> Any:  # pylint: disable=invalid-name
        # SeleniumBase 4.44.20 passes three unconsumed PIPE handles to Chrome.
        # Chrome and its children can fill those buffers, preventing the DevTools
        # port from becoming responsive or hanging the Calibre worker entirely.
        # Current SeleniumBase sends the same streams to DEVNULL.
        quiet_kwargs = dict(kwargs)
        for stream_name in ("stdin", "stdout", "stderr"):
            if quiet_kwargs.get(stream_name) == self._subprocess_module.PIPE:
                quiet_kwargs[stream_name] = self._subprocess_module.DEVNULL
        return self._subprocess_module.Popen(*args, **quiet_kwargs)


def configure_legacy_uc_subprocess(
    undetected_module: Any,
    version_info: Optional[Sequence[int]] = None,
) -> bool:
    """Backport non-blocking Chrome stdio handling to Python 3.8/3.9 vendors."""
    if browser_vendor_branch(version_info) == "current":
        return False
    subprocess_module = getattr(undetected_module, "subprocess", None)
    if isinstance(subprocess_module, _LegacyUcSubprocessProxy):
        return True
    if subprocess_module is None or not hasattr(subprocess_module, "Popen"):
        raise RuntimeError("Legacy SeleniumBase has no usable subprocess module")
    undetected_module.subprocess = _LegacyUcSubprocessProxy(subprocess_module)
    return True


def _native_macos_browser_command(command: List[str]) -> List[str]:
    """Prefer the ARM slice of a universal browser when Calibre runs in Rosetta."""
    if sys.platform != "darwin":
        return command
    try:
        translated = subprocess.run(
            ["/usr/sbin/sysctl", "-in", "sysctl.proc_translated"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return command
    if translated.returncode == 0 and translated.stdout.strip() == "1":
        # arch execs the browser, preserving its PID for supervisor cleanup.
        # Keep Intel as a fallback for browsers without an ARM slice.
        return ["/usr/bin/arch", "-arm64", "-x86_64", *command]
    return command


def _browser_debug_port() -> int:
    """Choose a free loopback port instead of UC's shared default of 9222."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class _SandboxedChromeSubprocessProxy:
    """Enforce sandbox policy on SeleniumBase's final Chrome command line."""

    _UNSAFE_SWITCHES = frozenset(
        {"--no-sandbox", "--disable-setuid-sandbox", "--disable-namespace-sandbox", "--disable-seccomp-filter-sandbox"}
    )

    def __init__(self, subprocess_module: Any, inside_flatpak: bool, capture_output: bool = False):
        self._subprocess_module = subprocess_module
        self.inside_flatpak = inside_flatpak
        self.capture_output = capture_output

    def __getattr__(self, name: str) -> Any:
        return getattr(self._subprocess_module, name)

    def Popen(self, args: Any, **kwargs: Any) -> Any:  # pylint: disable=invalid-name
        # Both supported SeleniumBase versions add --no-sandbox themselves on
        # Linux. Filtering chromium_arg alone cannot override those defaults.
        if not isinstance(args, (list, tuple)) or kwargs.get("shell"):
            raise RuntimeError("Chrome must be launched with an explicit argument list and without a shell")
        command = list(args)
        if not self.inside_flatpak:
            command = [arg for arg in command if arg.split("=", 1)[0] not in self._UNSAFE_SWITCHES]
        if self.capture_output:
            # The disposable worker's stderr already points to Calibre's log
            # file. Never create PIPEs here: no thread consumes those streams.
            kwargs["stdout"] = kwargs["stderr"] = 2
            command.append("--enable-logging=stderr")
        launch_command = _native_macos_browser_command(command)
        if self.capture_output and launch_command != command:
            print("Chrome launch: preferring ARM64 from a Rosetta caller", file=sys.stderr, flush=True)
        return self._subprocess_module.Popen(launch_command, **kwargs)


def configure_browser_sandbox(undetected_module: Any, inside_flatpak: bool, capture_output: bool = False) -> None:
    """Scope final-argument filtering to Chrome, without changing global subprocess."""
    subprocess_module = undetected_module.subprocess
    if isinstance(subprocess_module, _SandboxedChromeSubprocessProxy):
        subprocess_module.inside_flatpak = inside_flatpak
        subprocess_module.capture_output = capture_output
    else:
        undetected_module.subprocess = _SandboxedChromeSubprocessProxy(
            subprocess_module, inside_flatpak, capture_output
        )


@contextmanager
def _capture_chromedriver_log(log_path):
    """Capture startup negotiation separately from Python's repeated stack dumps."""
    if not log_path:
        yield
        return
    service_module: Any = importlib.import_module("selenium.webdriver.chrome.service")
    original_service = service_module.Service

    def diagnostic_service(*args, **kwargs):
        kwargs["log_output"] = log_path
        kwargs["service_args"] = [*(kwargs.get("service_args") or ()), "--verbose"]
        return original_service(*args, **kwargs)

    # Only the disposable worker's vendored service module is changed, and
    # only during Driver construction. Selenium owns and closes the log file.
    service_module.Service = diagnostic_service
    try:
        yield
    finally:
        service_module.Service = original_service


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


def _fetch_page_in_process(
    url,
    plugin_name,
    wait_for_element=None,
    not_found_marker=None,
    secondary_wait_element=None,
    max_wait=30,
    log_func=None,
    user_data_dir=None,
    search_fallback_url=None,
    capture_worker_output=False,
    chromedriver_log_path=None,
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
        secondary_wait_element: Optional content marker. Search pages require
            actual populated result nodes; an empty loading shell is a failure.
        max_wait: Maximum seconds to wait for page load
        log_func: Optional logging function to route errors to calibre's job log
        user_data_dir: Parent-owned profile for an installed browser worker.
            If omitted, this function creates and removes its own profile.

    Returns:
        Page HTML as string, or None on error
    """

    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    unavailable_reason = browser_automation_unavailable_reason()
    if unavailable_reason:
        _log(unavailable_reason)
        return None

    # Calibre can keep multiple plugins in one interpreter. Serialize the short
    # period where absolute Selenium imports require temporary sys.path,
    # sys.meta_path, and sys.modules changes, then restore the host state.
    _BROWSER_IMPORT_LOCK.acquire()
    original_stdout, original_stderr, original_excepthook = sys.stdout, sys.stderr, sys.excepthook
    original_sys_path = None
    original_meta_path = None
    original_vendor_modules = None
    original_path_env = None
    path_env_was_present = False
    path_env_captured = False
    owns_profile = user_data_dir is None
    try:
        # Keep all state capture inside the protected try. If another thread
        # mutates sys.modules while the snapshot is being built, the finally
        # block must still release the global import lock.
        original_sys_path = list(sys.path)
        original_meta_path = list(sys.meta_path)
        original_vendor_modules = snapshot_browser_vendor_modules(plugin_name)
        path_env_was_present = "PATH" in os.environ
        original_path_env = os.environ.get("PATH")
        path_env_captured = True

        # Use a stable driver directory under the user's home dir so chromedriver
        # persists across calibre sessions (calibre rotates its own temp dir each run)
        stable_base = os.environ.get("CALIBRE_SELENIUM_HOME") or os.path.join(
            os.path.expanduser("~"), ".calibre_selenium"
        )
        sb_drivers_dir = os.path.abspath(os.path.join(stable_base, "drivers"))
        downloads_dir = os.path.abspath(os.path.join(stable_base, "downloads"))

        # Each Chrome instance gets a fresh throw-away profile in the system TEMP dir.
        # Using TEMP (not stable_base) keeps paths short (avoids Windows MAX_PATH issues)
        # and ensures the OS auto-cleans these on reboot even if we crash before cleanup.
        # Installed calls receive a parent-owned directory so even a killed
        # worker's profile can be removed. Direct calls clean up locally.
        if owns_profile:
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

        # Add the plugin root and matching browser dependency branch to sys.path
        # before module clearing and before VendoredPackageFinder is set up.
        _plugin_dir_early = resolve_browser_vendor_source(plugin_name)
        if _plugin_dir_early not in sys.path:
            sys.path.insert(0, _plugin_dir_early)
        _vendor_paths = configure_browser_vendor_path(_plugin_dir_early)
        configure_browser_vendor_metadata(_plugin_dir_early, _vendor_paths)
        _log(f"Browser dependency branch: {browser_vendor_branch()}")

        # Clear cached SeleniumBase/fasteners modules to ensure fresh import.
        # Clear both the calibre_plugins.{plugin_name}.* namespace AND the bare
        # selenium/seleniumbase namespace - the latter is used when the zip is on sys.path.
        clear_browser_vendor_modules(plugin_name)

        # Install import hook for vendored packages if not already installed
        # Check if we already have a finder for this plugin
        existing_finder = None
        for meta_finder in sys.meta_path:
            if isinstance(meta_finder, VendoredPackageFinder) and meta_finder.plugin_name == plugin_name:
                existing_finder = meta_finder
                break

        if not existing_finder:
            finder: VendoredPackageFinder = VendoredPackageFinder(  # type: ignore[assignment]
                plugin_name,
                plugin_dir=_plugin_dir_early,
                package_roots=_vendor_paths,
            )
            sys.meta_path.insert(0, finder)  # type: ignore[arg-type]

        # The plugin's package directory is on sys.path so vendored packages
        # can be imported directly via zipimport. This is required in calibre GUI
        # mode where the plugin is loaded from a zip that isn't on sys.path.
        #
        # Browser packages sit below browser_vendor/ inside the plugin ZIP. The
        # resolved source supports both newer Calibre virtual paths and Calibre
        # 5's ``<calibre Plugin Loader>`` __file__ placeholder.
        # NOTE: also inserted early (before module clearing) as _plugin_dir_early above.
        plugin_dir = _plugin_dir_early
        _log("Vendored browser dependencies configured")
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
            clear_browser_vendor_modules(plugin_name)
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
        # SeleniumBase's compatibility helper may downgrade HTTPS to HTTP after
        # a certificate error. Runtime executable downloads must instead stay
        # on an explicit set of Google-owned TLS origins, including redirects.
        configure_secure_driver_downloads(sb_install)
        detect_b_ver = importlib.import_module("seleniumbase.core.detect_b_ver")
        configure_macos_browser_detection(detect_b_ver)
        download_helper = importlib.import_module("seleniumbase.core.download_helper")
        fasteners_module = importlib.import_module("fasteners")
        patcher = importlib.import_module("seleniumbase.undetected.patcher")
        undetected_module = importlib.import_module("seleniumbase.undetected")
        if configure_legacy_uc_subprocess(undetected_module):
            _log("Applied non-blocking Chrome stdio handling for legacy SeleniumBase")
        configure_browser_sandbox(
            undetected_module,
            inside_flatpak=bool(os.environ.get("FLATPAK_ID")),
            capture_output=capture_worker_output,
        )

        sb_install.DRIVER_DIR = sb_drivers_dir  # type: ignore[attr-defined]
        download_helper.downloads_path = downloads_dir  # type: ignore[attr-defined]
        patcher.Patcher.data_path = sb_drivers_dir

        _log("Loading Chrome launcher")
        browser_launcher = importlib.import_module("seleniumbase.core.browser_launcher")
        _log("Chrome launcher loaded; detecting installed browser version")

        is_windows = platform.system() == "Windows"
        uc_driver_name = "uc_driver.exe" if is_windows else "uc_driver"
        chromedriver_name = "chromedriver.exe" if is_windows else "chromedriver"

        # browser_launcher.py computes DRIVER_DIR from drivers.__file__ at import time.
        # When loaded from a zip, drivers.__file__ is a virtual path inside the zip.
        # Save it now; after verifying the persistent download cache below, all
        # launch-time driver paths are redirected to a per-worker real directory.
        old_driver_dir = getattr(browser_launcher, "DRIVER_DIR", None)

        # Install chromedriver if needed (SeleniumBase downloads it as "chromedriver").
        # The stable cache is shared by all Calibre worker processes, so its full
        # check/install/copy sequence must be protected by an interprocess lock.
        chromedriver_path = os.path.join(sb_drivers_dir, chromedriver_name)
        runtime_drivers_dir = os.path.join(user_data_dir, "drivers")
        os.makedirs(runtime_drivers_dir, exist_ok=True)
        runtime_chromedriver_path = os.path.join(runtime_drivers_dir, chromedriver_name)
        uc_driver_path = os.path.join(runtime_drivers_dir, uc_driver_name)

        flatpak_chrome = _find_flatpak_chrome()
        if flatpak_chrome:
            _log(f"Directly runnable Chrome binary found in Flatpak storage: {flatpak_chrome!r}")
        elif os.environ.get("FLATPAK_ID"):
            _log(
                "No directly runnable Chrome binary was found in Flatpak storage. "
                "SeleniumBase will check for another Chrome binary visible inside the Calibre sandbox; "
                "non-browser fallbacks remain available if none is found."
            )
        browser_major_version = _installed_browser_major_version(detect_b_ver, flatpak_chrome)
        if browser_major_version is not None:
            _log(f"Detected installed Chrome major version: {browser_major_version}")

        prepare_cached_chromedriver(
            sb_install=sb_install,
            interprocess_lock_class=fasteners_module.InterProcessLock,
            stable_base=stable_base,
            chromedriver_path=chromedriver_path,
            runtime_chromedriver_path=runtime_chromedriver_path,
            log_func=_log,
            browser_major_version=browser_major_version,
        )

        sb_install.DRIVER_DIR = runtime_drivers_dir  # type: ignore[attr-defined]
        patcher.Patcher.data_path = runtime_drivers_dir
        browser_launcher.DRIVER_DIR = runtime_drivers_dir  # type: ignore[attr-defined]
        browser_launcher.LOCAL_UC_DRIVER = uc_driver_path  # type: ignore[attr-defined]
        browser_launcher.LOCAL_CHROMEDRIVER = runtime_chromedriver_path  # type: ignore[attr-defined]
        path_env = os.environ.get("PATH", "")
        if old_driver_dir:
            path_env = path_env.replace(old_driver_dir + os.pathsep, "")
            path_env = path_env.replace(old_driver_dir, "")
        if runtime_drivers_dir not in path_env:
            path_env = runtime_drivers_dir + os.pathsep + path_env
        os.environ["PATH"] = path_env

        uc_digest = prepare_uc_driver(runtime_chromedriver_path, uc_driver_path, patcher.Patcher)
        _log(f"uc_driver rebuilt and verified (SHA-256: {uc_digest})")

        Driver = importlib.import_module("seleniumbase.plugins.driver_manager").Driver  # pylint: disable=invalid-name

        driver = None
        validated_page = None
        try:
            chrome_args = _build_chrome_args(
                user_data_dir,
                inside_flatpak=bool(os.environ.get("FLATPAK_ID")),
                in_ci=bool(os.environ.get("CI")),
            )
            debug_port = _browser_debug_port()
            # Both vendored launchers propagate this argument to UC's
            # debuggerAddress as well as Chrome's command line.
            chrome_args.append(f"--remote-debugging-port={debug_port}")
            _log(f"Chrome debugging endpoint: 127.0.0.1:{debug_port}")

            _log("Starting Chrome (startup is included in the browser time limit)...")
            with _capture_chromedriver_log(chromedriver_log_path if capture_worker_output else None):
                driver = Driver(
                    uc=True,
                    headless=False,
                    chromium_arg=chrome_args,
                    binary_location=flatpak_chrome,
                )

            # SeleniumBase can replace uc_driver when it detects a Chrome-version
            # mismatch. Downloads are TLS/host restricted above; persist and verify
            # the final bytes so the executable used by this session is covered too.
            launched_digest = _sha256_file(uc_driver_path)
            if launched_digest != uc_digest:
                uc_digest = record_driver_integrity(uc_driver_path)
                _log(f"SeleniumBase refreshed uc_driver; verified SHA-256: {uc_digest}")
            verify_driver_integrity(uc_driver_path)

            try:
                _chrome_ver = driver.capabilities.get("browserVersion") or driver.capabilities.get("version", "unknown")
                _driver_ver = (driver.capabilities.get("chrome", {}) or {}).get("chromedriverVersion", "unknown")
                if isinstance(_driver_ver, str):
                    _driver_ver = _driver_ver.split(" ")[0]  # strip trailing platform info
                _log(f"Chrome version: {_chrome_ver}, chromedriver version: {_driver_ver}")
            except Exception:  # pylint: disable=broad-except
                pass

            from .common_romanceio_webengine import navigate_chrome

            validated_page = navigate_chrome(
                driver,
                {
                    "url": url,
                    "max_wait": max_wait,
                    "wait_for_element": wait_for_element,
                    "not_found_marker": not_found_marker,
                    "secondary_wait_element": secondary_wait_element,
                    "search_fallback_url": search_fallback_url,
                },
                _log,
            )
            return validated_page

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
            if "this version of chromedriver only supports" in msg.lower():
                _log(
                    f"Chrome version mismatch: {e}\n"
                    "  The downloaded chromedriver doesn't match your installed Chrome version.\n"
                    "  Delete the managed drivers folder and retry."
                )
                return None
            _log(f"Chrome error: {type(e).__name__}: {e}")
            import traceback

            _log(traceback.format_exc())
            return None
        finally:
            if driver:
                try:
                    from .common_romanceio_webengine import clearance_page_valid

                    if (
                        urlparse(url).scheme == "https"
                        and urlparse(url).hostname == "www.romance.io"
                        and clearance_page_valid(validated_page, {"url": url})
                    ):
                        try:
                            from .common_romanceio_session import save_clearance

                            if save_clearance(
                                driver.get_cookies(), driver.execute_script("return navigator.userAgent")
                            ):
                                _log("Saved temporary Cloudflare clearance; subsequent requests can use direct HTTP")
                        except Exception as session_error:  # pylint: disable=broad-except
                            # Never log cookie values or a WebDriver response containing them.
                            _log(f"Could not save browser clearance ({type(session_error).__name__})")
                    _log("Closing Chrome...")
                    driver.quit()
                    _log("Chrome closed")
                except Exception as quit_err:  # pylint: disable=broad-except
                    _log(f"Error closing driver: {quit_err}")
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
            # Log only structural path information; absolute paths can identify users.
            _plugin_entries = [p for p in sys.path if "calibre" in p.lower() or p.endswith(".zip")]
            _log(f"sys.path has {len(_plugin_entries)} Calibre/ZIP entries")
            # Verify the zip contains the seleniumbase files we need.
            _zip_path = _plugin_dir_early
            if os.path.isfile(_zip_path) and _zf.is_zipfile(_zip_path):
                with _zf.ZipFile(_zip_path) as _zf_obj:
                    _sb_files = [
                        n for n in _zf_obj.namelist() if "/seleniumbase/" in n and n.startswith("browser_vendor/")
                    ]
                    _log(f"Zip contains {len(_sb_files)} seleniumbase files")
                    _missing = [
                        f
                        for f in [
                            "browser_vendor/shared/seleniumbase/__init__.py",
                            "browser_vendor/shared/seleniumbase/core/browser_launcher.py",
                            "browser_vendor/current/seleniumbase/__init__.py",
                            "browser_vendor/current/seleniumbase/core/browser_launcher.py",
                        ]
                        if f not in _sb_files
                    ]
                    if _missing:
                        _log(f"WARNING: missing from zip: {_missing}")
            else:
                _log("Vendored dependency source is a directory rather than a plugin ZIP")
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

        _log(traceback.format_exc())
        return None
    finally:
        # SeleniumBase initializes Colorama and its traceback hook on import.
        # Reimports otherwise stack StreamWrappers until logging itself raises
        # RecursionError (about 250 calls with piped output). Workers isolate
        # installed use, but standalone Calibre diagnostics also need restoration.
        sys.stdout, sys.stderr, sys.excepthook = original_stdout, original_stderr, original_excepthook
        # Direct calls clean up after quit, including failures during setup.
        # Installed workers leave their profile to the supervising process.
        if owns_profile and user_data_dir and os.path.isdir(user_data_dir):
            shutil.rmtree(user_data_dir, ignore_errors=True)
        if original_vendor_modules is not None:
            restore_browser_vendor_modules(plugin_name, original_vendor_modules)
        if original_sys_path is not None:
            sys.path[:] = original_sys_path
        if original_meta_path is not None:
            sys.meta_path[:] = original_meta_path
        if path_env_captured:
            if path_env_was_present:
                os.environ["PATH"] = original_path_env or ""
            else:
                os.environ.pop("PATH", None)
        _BROWSER_IMPORT_LOCK.release()


def _fetch_page_worker(request: Dict[str, Any]) -> Dict[str, Any]:
    """Calibre IPC entry point for a disposable Qt or Chrome browser worker."""
    logs: List[str] = []

    def log(message: str) -> None:
        if request.get("transport_dir"):
            _write_browser_log(request, message)
        else:
            logs.append(message)

    diagnostics = None
    if request.get("capture_worker_output"):
        import faulthandler

        diagnostics = faulthandler
        diagnostics.enable()
        # Opt-in local CI fixtures only. A hung import/version probe otherwise
        # leaves no Python traceback when the supervisor terminates the worker.
        diagnostics.dump_traceback_later(20, repeat=True)
    try:
        from .common_romanceio_webengine import fetch_page as fetch_embedded_page

        if request.get("backend") == "chrome":
            try:
                from calibre.constants import sanitize_env_vars
            except ImportError:
                from calibre.gui2 import sanitize_env_vars

            # Chrome and ChromeDriver are external binaries: Calibre's bundled
            # libraries can crash them before a WebDriver session is created.
            # Cover version probes, launch, and reconnect in this disposable
            # worker only; the embedded Qt worker needs Calibre's environment.
            with sanitize_env_vars():
                page = _fetch_page_in_process(
                    request["url"],
                    request["plugin_name"],
                    wait_for_element=request.get("wait_for_element"),
                    not_found_marker=request.get("not_found_marker"),
                    secondary_wait_element=request.get("secondary_wait_element"),
                    max_wait=request.get("max_wait", 30),
                    log_func=log,
                    user_data_dir=request.get("user_data_dir"),
                    search_fallback_url=request.get("search_fallback_url"),
                    capture_worker_output=bool(request.get("capture_worker_output")),
                    chromedriver_log_path=(
                        os.path.join(request["transport_dir"], "chromedriver.log")
                        if request.get("capture_worker_output") and request.get("transport_dir")
                        else None
                    ),
                )
        else:
            page = fetch_embedded_page(request, log)
        return {"page": page, "logs": logs, "error_type": None, "error_message": None}
    except Exception as error:  # The IPC response preserves failures without retrying the engine.
        import traceback

        log(_redact_log_text(traceback.format_exc()))
        return {
            "page": None,
            "logs": logs,
            "error_type": "BrowserFetchError",
            "error_message": str(error),
        }
    finally:
        if diagnostics is not None:
            diagnostics.cancel_dump_traceback_later()


def _is_installed_plugin_module(plugin_name: str) -> bool:
    expected_name = f"calibre_plugins.{plugin_name}.common_romanceio_fetch_helper"
    return __name__ == expected_name


def wait_for_browser_processes(processes: Sequence[Any], timeout: float) -> List[Any]:
    """Wait for tracked identities, excluding PIDs already reused by another process."""
    import psutil

    # Windows Process.wait() opens a handle by PID without checking creation
    # time. Selenium reconnects restart ChromeDriver frequently, so an exited
    # driver's PID may already belong to a different, unrelated process.
    pending = [process for process in processes if process.is_running()]
    _, alive = psutil.wait_procs(pending, timeout=timeout)
    # A PID can also be reused during the bounded wait. Never treat the new
    # process as a surviving browser or try to kill it on that basis.
    return [process for process in alive if process.is_running()]


class _BrowserWorkerResources:
    """Own the profile and track descendants before Calibre can kill the worker."""

    def __init__(self, timeout: float, log_func: Callable):
        # Native psutil is supplied by Calibre, never by the browser vendor.
        import psutil

        self.psutil = psutil
        self.log_func = log_func
        self.worker: Any = None
        self.process: Any = None
        self.descendants: set = set()
        self.deadline = time.monotonic() + timeout
        self.next_scan = 0.0
        self.profile = tempfile.mkdtemp(prefix="calibre_sb_")

    def watch(self, worker: Any) -> None:
        self.worker = worker
        self.process = self.psutil.Process(worker.pid)

    def _collect_descendants(self, process: Any) -> None:
        try:
            self.descendants.update(process.children(recursive=True))
        except self.psutil.NoSuchProcess:
            pass

    def heartbeat(self) -> bool:
        now = time.monotonic()
        if now >= self.next_scan or now >= self.deadline:
            self._collect_descendants(self.process)
            self.next_scan = now + 0.25
        # Calibre calls this before forcibly killing the worker. The final scan
        # preserves process identities even after Chrome is reparented on exit.
        return now < self.deadline

    def close(self) -> None:
        try:
            if self.process is not None:
                self._collect_descendants(self.process)
            for process in list(self.descendants):
                self._collect_descendants(process)
        except self.psutil.Error as error:
            self.log_func(f"Could not inspect browser descendants during cleanup: {error}")
        finally:
            if self.worker is not None:
                # run_job also starts an asynchronous kill; wait for the worker
                # here so it cannot launch another browser after cleanup begins.
                self.worker.kill()
                if self.process is not None:
                    try:
                        self.process.wait(timeout=5)
                    except self.psutil.Error as error:
                        self.log_func(f"Could not wait for browser worker exit: {error}")

        for process in self.descendants:
            try:
                # psutil verifies creation time before signalling, protecting
                # unrelated processes if the operating system reuses a PID.
                process.terminate()
            except self.psutil.NoSuchProcess:
                pass
            except self.psutil.Error as error:
                self.log_func(f"Could not terminate browser descendant: {error}")
        alive = wait_for_browser_processes(list(self.descendants), timeout=2)
        for process in alive:
            try:
                process.kill()
            except self.psutil.NoSuchProcess:
                pass
            except self.psutil.Error as error:
                self.log_func(f"Could not kill browser descendant: {error}")
        alive = wait_for_browser_processes(alive, timeout=2)
        if alive:
            self.log_func("Browser descendants did not exit; retaining their temporary profile")
            return
        try:
            shutil.rmtree(self.profile)
        except OSError as error:
            self.log_func(f"Could not remove temporary browser profile: {error}")


def _write_browser_log(request: Dict[str, Any], message: Any) -> None:
    """Flush each redacted message so killing a job does not lose its diagnostics."""
    with open(os.path.join(request["transport_dir"], "progress.jsonl"), "a", encoding="utf-8") as stream:
        stream.write(json.dumps(_redact_log_text(message)) + "\n")


def _browser_owner_alive(request: Dict[str, Any]) -> bool:
    import psutil

    try:
        owner = psutil.Process(request["owner_pid"])
        return owner.create_time() == request["owner_created"] and owner.is_running()
    except psutil.NoSuchProcess:
        return False


def _finish_browser_worker_output(
    log_path: Optional[str], failed: bool, log: Callable, label: str = "Browser worker native output"
) -> None:
    """Report bounded native diagnostics for opted-in smoke tests, then remove them."""
    if not log_path:
        return
    try:
        if failed:
            with open(log_path, "rb") as stream:
                size = stream.seek(0, os.SEEK_END)
                stream.seek(0)
                output = stream.read(16384)
                if size > 16384:
                    stream.seek(max(16384, size - 16384))
                    if size > 32768:
                        output += b"\n... middle of log omitted ...\n"
                    output += stream.read(16384)
                decoded = output.decode("utf-8", errors="replace").strip()
            log(_redact_log_text(f"{label} (first/last 16 KiB, up to 32 KiB):\n" + (decoded or "(empty)")))
    except OSError as error:
        log(f"Could not read browser worker native output: {type(error).__name__}")
    finally:
        try:
            os.remove(log_path)
        except FileNotFoundError:
            pass
        except OSError as error:
            log(f"Could not remove browser worker native output: {type(error).__name__}")


def _supervise_browser_worker(request: Dict[str, Any]) -> Dict[str, Any]:
    """Remain alive after Calibre cancels the caller, then reap its browser tree.

    This process does no Qt rendering. Its heartbeat covers setup, navigation,
    and quit, even when any of those blocks inside the actual browser worker.
    """
    from calibre.utils.ipc.simple_worker import two_part_fork_job

    def log(message: Any) -> None:
        _write_browser_log(request, message)

    resources = _BrowserWorkerResources(request["worker_timeout"], log)
    reason = "Browser worker failed"
    # Only the local smoke harness opts in. Normal website fetches continue to
    # discard native output, which may contain untrusted page diagnostics.
    capture_output = bool(request.get("capture_worker_output"))
    native_log_path = None
    failed = True

    def heartbeat() -> bool:
        nonlocal reason
        within_budget = resources.heartbeat()
        if not _browser_owner_alive(request) or os.path.exists(os.path.join(request["transport_dir"], "cancel")):
            reason = "Browser cancelled; stopping its worker and browser processes"
            return False
        if not within_budget:
            reason = f"Browser exceeded its {request['worker_timeout']:g}s total time limit (including startup/navigation/quit)"
            return False
        return True

    try:
        if not _browser_owner_alive(request):
            return {"page": None, "error_type": "BrowserFetchError", "error_message": "Caller exited"}
        log(f"Browser time limit: {request['worker_timeout']:g}s including setup, navigation, and shutdown")
        run_job = two_part_fork_job()
        if capture_output:
            native_log_path = run_job.worker.log_path
        resources.watch(run_job.worker)
        response = run_job(
            __name__,
            "_fetch_page_worker",
            args=({**request, "user_data_dir": resources.profile},),
            heartbeat=heartbeat,
            no_output=not capture_output,
        )["result"]
        if not isinstance(response, dict):
            raise BrowserFetchError("Browser worker returned an invalid response")
        failed = bool(response.get("error_type")) or not response.get("page")
        return response
    except Exception as error:  # pylint: disable=broad-except
        log(f"{reason}: {type(error).__name__}: {error}")
        if capture_output and resources.worker is not None:
            log(f"Browser worker exit code before cleanup: {getattr(resources.worker, 'returncode', None)}")
        return {"page": None, "error_type": "BrowserFetchError", "error_message": reason}
    finally:
        try:
            resources.close()
        finally:
            _finish_browser_worker_output(native_log_path, failed, log)
            if capture_output and request.get("backend") == "chrome":
                _finish_browser_worker_output(
                    os.path.join(request["transport_dir"], "chromedriver.log"),
                    failed,
                    log,
                    "ChromeDriver startup output",
                )
            if not _browser_owner_alive(request):
                shutil.rmtree(request["transport_dir"], ignore_errors=True)


def _fetch_page_via_calibre_worker(
    request: Dict[str, Any], log_func: Optional[Callable], abort: Optional[Any] = None
) -> Optional[str]:
    """Stream progress from a supervised, disposable Calibre browser worker."""
    import psutil
    from calibre.utils.ipc.simple_worker import fork_job

    def log(message: Any) -> None:
        safe_message = _redact_log_text(message)
        if log_func:
            log_func(safe_message)
        else:
            print(safe_message, flush=True)

    if abort is not None and abort.is_set():
        raise BrowserFetchError("Browser cancelled before startup")
    from .common_romanceio_transport import current_budget, remaining

    abort = current_budget() or abort
    worker_timeout = remaining(90 if request.get("backend") == "chrome" else 45)
    owner = psutil.Process()
    transport = tempfile.mkdtemp(prefix="calibre_sb_log_")
    request = {
        **request,
        "transport_dir": transport,
        "owner_pid": owner.pid,
        "owner_created": owner.create_time(),
        "worker_timeout": worker_timeout,
    }
    position = 0
    next_read = 0.0

    def progress(force: bool = False) -> bool:
        nonlocal position, next_read
        if abort is not None and abort.is_set():
            with open(os.path.join(transport, "cancel"), "a", encoding="utf-8"):
                pass
        if not force and time.monotonic() < next_read:
            return True
        next_read = time.monotonic() + 0.1
        try:
            with open(os.path.join(transport, "progress.jsonl"), encoding="utf-8") as stream:
                stream.seek(position)
                while True:
                    line = stream.readline()
                    if not line.endswith("\n"):
                        break
                    log(json.loads(line))
                    position = stream.tell()
        except FileNotFoundError:
            pass
        # Never kill the supervisor on cancellation: it must finish cleanup.
        # The supervisor enforces the deadline on the browser worker itself.
        return True

    try:
        response = fork_job(
            __name__,
            "_supervise_browser_worker",
            args=(request,),
            heartbeat=progress,
            no_output=True,
        )["result"]
    except Exception as error:  # pylint: disable=broad-except
        raise BrowserFetchError(f"Browser supervisor failed: {type(error).__name__}: {error}") from error
    finally:
        progress(force=True)
        shutil.rmtree(transport, ignore_errors=True)

    if not isinstance(response, dict):
        raise BrowserFetchError("Browser worker returned an invalid response")
    for message in response.get("logs") or []:
        log(message)
    error_type = response.get("error_type")
    if error_type:
        raise BrowserFetchError(_redact_log_text(response.get("error_message") or error_type))
    page = response.get("page")
    if not isinstance(page, str) or not page:
        raise BrowserFetchError("Browser did not return a page; see the preceding browser log")
    return page


def fetch_page(
    url,
    plugin_name,
    wait_for_element=None,
    not_found_marker=None,
    secondary_wait_element=None,
    max_wait=30,
    log_func=None,
    abort=None,
    allow_chrome_fallback=True,
    prefer_chrome=False,
    backend=None,
):
    """Fetch a page in an isolated worker when running as an installed plugin."""
    request = {
        "url": url,
        "plugin_name": plugin_name,
        "wait_for_element": wait_for_element,
        "not_found_marker": not_found_marker,
        "secondary_wait_element": secondary_wait_element,
        "max_wait": max_wait,
    }

    from .common_romanceio_transport import current_budget, remaining
    from urllib.parse import parse_qs, urlencode

    budget = current_budget()
    abort = budget or abort
    # A browser may be called inside a JSON retry callback after a prior 429.
    # Apply the same cooldown before startup, outside the browser worker budget.
    from .common_romanceio_search_orchestrator import wait_for_rate_limit

    if not wait_for_rate_limit(log_func or print, abort):
        raise BrowserFetchError("Browser cancelled during rate-limit cooldown")
    parsed_url = urlparse(url)
    if parsed_url.path == "/json/search_books":
        query = parse_qs(parsed_url.query).get("search", [""])[0]
        request["search_fallback_url"] = f"{parsed_url.scheme}://{parsed_url.netloc}/search?" + urlencode({"q": query})
    request["max_wait"] = remaining(max_wait)

    def fetch(request):
        if _is_installed_plugin_module(plugin_name):
            return _fetch_page_via_calibre_worker(request, log_func, abort)
        # Standalone Calibre diagnostics own their process already.
        response = _fetch_page_worker(request)
        for message in response["logs"]:
            (log_func or print)(message)
        if response["error_type"] or not response["page"]:
            raise BrowserFetchError(response["error_message"] or "Browser returned no page")
        return response["page"]

    backends: Sequence[str] = ("chrome", "embedded") if prefer_chrome else ("embedded", "chrome")
    if not allow_chrome_fallback:
        backends = ("embedded",)
    if backend is not None:
        if backend not in ("embedded", "chrome"):
            raise ValueError(f"Unknown browser backend: {backend}")
        backends = (backend,)
    for index, backend in enumerate(backends):
        if budget and backend in budget.failed_browsers:
            (log_func or print)(f"Skipping {backend}: its browser session already failed in this lookup")
            continue
        if abort is not None and abort.is_set():
            raise BrowserFetchError("Browser cancelled before startup")
        try:
            return fetch({**request, "backend": backend})
        except BrowserFetchError as error:
            (log_func or print)(_redact_log_text(f"{backend.capitalize()} browser failed: {error}"))
            if budget:
                budget.failed_browsers.add(backend)
            if (abort is not None and abort.is_set()) or index == len(backends) - 1:
                raise
            next_backend = backends[index + 1]
            (log_func or print)(f"{backend.capitalize()} browser failed; trying {next_backend} once.")
    raise BrowserFetchError("No untried browser remains for this lookup")


def fetch_book_page_http(romanceio_id: str, log_func: Optional[Callable] = None, timeout: int = 30) -> tuple:
    """Fetch a Romance.io book page using a simple HTTP GET request (no Chrome).

    Romance.io renders book pages server-side (SSR), so all tag, rating, and metadata
    content is present in the initial HTML response without JavaScript execution.
    This makes a lightweight HTTP GET fast and Chrome-free.

    Args:
        romanceio_id: Romance.io book ID
        log_func: Optional logging function
        timeout: Socket timeout in seconds (default: 30). Callers should pass a value
            appropriate to their retry budget (e.g. _JSON_REQUEST_TIMEOUT_SECS).

    Returns:
        Tuple of (page_html, is_valid):
        - page_html: HTML string if a response was received, None on network error
        - is_valid: True if the page is a valid book page, False if 404 or wrong content

    Raises:
        RuntimeError: On network/connection errors (caller should retry or fall back)
    """
    from urllib.request import Request
    from urllib.error import HTTPError

    def _log(msg: str) -> None:
        if log_func:
            log_func(msg)

    url = f"https://www.romance.io/books/{romanceio_id}"
    _log(f"Lightweight HTTP fetch: requesting {url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    from .common_romanceio_session import clearance_headers, discard_clearance
    from .common_romanceio_transport import HttpRateLimitError, open_request

    cached_headers = clearance_headers(url)
    headers.update(cached_headers)
    if cached_headers:
        _log("Using cached Cloudflare clearance for direct page HTTP request")

    try:
        req = Request(url, headers=headers)
        with open_request(req, timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
        _log(f"Lightweight HTTP fetch: received {len(html)} bytes")

        not_found_text = "the page you are looking for can't be found"
        if not_found_text in html.lower():
            _log(f"Lightweight HTTP fetch: book {romanceio_id} not found (404 page content)")
            return html, False

        if "book-stats" not in html:
            # Cloudflare returned a JS-challenge or interstitial page instead of the book page.
            # Raising here causes the orchestrator to fall through to the browser fallback immediately
            # (after the configured number of retries).
            raise RuntimeError(
                f"Lightweight HTTP fetch: page missing expected content for {romanceio_id} "
                "(Cloudflare may be blocking plain HTTP requests - will try the next access method)"
            )

        return html, True

    except RuntimeError:
        raise
    except HTTPError as e:
        if e.code == 404:
            _log(f"Lightweight HTTP fetch: 404 for {romanceio_id}")
            return None, False
        if e.code == 403:
            discard_clearance(cached_headers.get("Cookie", ""))
            # Cloudflare or server is blocking plain HTTP requests to this page.
            # A typed failure lets the orchestrator skip futile HTTP retries.
            raise HttpAccessDeniedError(
                f"Lightweight HTTP fetch: 403 Forbidden for {romanceio_id} "
                "(HTTP access denied - will try the next access method)"
            ) from e
        if e.code == 429:
            raise HttpRateLimitError(
                f"Lightweight HTTP fetch: 429 Too Many Requests for {romanceio_id}",
                retry_after=e.headers.get("Retry-After") if e.headers is not None else None,
            ) from e
        raise RuntimeError(f"Lightweight HTTP fetch failed for {romanceio_id}: HTTP {e.code}") from e
    except Exception as e:
        raise RuntimeError(f"Lightweight HTTP fetch failed for {romanceio_id}: {type(e).__name__}: {e}") from e


def fetch_romanceio_book_page(url, plugin_name, log=None, abort=None, prefer_chrome=False, backend=None):
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
        abort=abort,
        prefer_chrome=prefer_chrome,
        backend=backend,
    )

    if not page_html:
        log_error("Failed to fetch page (browser timed out or crashed - see the job log)")
        return None, False

    if _not_found_text in page_html.lower():
        log_error(f"Invalid Romance.io ID (404): {url}")
        return page_html, False

    if "book-stats" not in page_html:
        log_error(f"Page missing book-stats element after waiting: {url}")
        return page_html, False

    return page_html, True
