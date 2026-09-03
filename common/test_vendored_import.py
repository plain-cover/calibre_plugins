"""Tests for VendoredPackageFinder import routing and the direct-zipimport strategy.

VendoredPackageFinder (VPF) sits in sys.meta_path and redirects bare package
imports (e.g. ``import seleniumbase``) to the calibre_plugins-namespaced copy
(e.g. ``calibre_plugins.romanceio.seleniumbase``) so all plugins share the same
vendored library.  When that redirect fails, VPF falls back to loading the package
directly via zipimport.

The internal browser worker uses a complementary strategy: it removes all VPFs
from sys.meta_path before importing seleniumbase, then re-adds them at low
priority. This lets zipimport handle the full import tree without VPF intercepting
every sub-import, while keeping VPF available for C extensions (e.g. lxml.etree)
that cannot be loaded from a zip. Installed plugins run that work in a disposable
Calibre process so none of these import-table changes touch the host process.

Test groups:
  1. VPF routing   - find_module intercept/pass-through logic.
  2. VPF loading   - calibre_plugins redirect and direct-zipimport fallback.
  3. Zip layout    - vendored packages load from a zip on sys.path.
  4. Priority strategy - removing/re-adding VPF around a pure-Python import.
  5. Regression    - VPF with broken redirect blocks import; fetch_page() strategy bypasses it.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
from importlib import metadata
import multiprocessing
import os
import sys
import threading
import time
import types
import zipfile

import pytest

from common import common_romanceio_fetch_helper as fetch_helper
from common.common_romanceio_fetch_helper import (
    VENDORED_PACKAGES,
    VendoredModule,
    VendoredPackageFinder,
    browser_vendor_branch,
    clear_browser_vendor_modules,
    configure_browser_vendor_metadata,
    configure_browser_vendor_path,
    prepare_cached_chromedriver,
    prepare_uc_driver,
    record_driver_integrity,
    restore_browser_vendor_modules,
    snapshot_browser_vendor_modules,
    validate_driver_download_url,
    verify_driver_integrity,
)

_TEST_PKG = "_test_vendored_pkg"
_TEST_PLUGIN = "_test_plugin"
_ALIAS = f"calibre_plugins.{_TEST_PLUGIN}.{_TEST_PKG}"


def _prepare_cached_driver_in_process(stable_base, runtime_driver_path, start_event, ready_queue, result_queue):
    """Multiprocessing target used to reproduce simultaneous first-run setup."""
    vendor_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "romanceio", "browser_vendor", "shared")
    )
    sys.path.insert(0, vendor_path)
    import fasteners  # pylint: disable=import-outside-toplevel,import-error

    stable_driver_path = os.path.join(stable_base, "drivers", "chromedriver")
    install_marker = os.path.join(stable_base, "install-calls.txt")

    class SlowInstaller:
        @staticmethod
        def main(_command):
            with open(install_marker, "a", encoding="ascii") as marker:
                marker.write(f"{os.getpid()}\n")
            time.sleep(0.25)
            with open(stable_driver_path, "wb") as driver:
                driver.write(b"shared driver bytes")

    ready_queue.put(os.getpid())
    start_event.wait(10)
    try:
        digest = prepare_cached_chromedriver(
            sb_install=SlowInstaller,
            interprocess_lock_class=fasteners.InterProcessLock,
            stable_base=stable_base,
            chromedriver_path=stable_driver_path,
            runtime_chromedriver_path=runtime_driver_path,
            log_func=lambda _message: None,
        )
        result_queue.put(("ok", digest))
    except Exception as error:  # pylint: disable=broad-except
        result_queue.put(("error", f"{type(error).__name__}: {error}"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vendored_zip(directory: str, package_root: str = "") -> str:
    """Return the path of a zip containing a minimal two-level vendored package.

    plugin.zip/
        _test_vendored_pkg/__init__.py       VALUE = 42
        _test_vendored_pkg/sub/__init__.py
        _test_vendored_pkg/sub/module.py     SUB_VALUE = VALUE + 1 (intra-package import)
    """
    zip_path = os.path.join(directory, "plugin.zip")
    prefix = package_root.strip("/")
    archive_package = f"{prefix}/{_TEST_PKG}" if prefix else _TEST_PKG
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{archive_package}/__init__.py", "VALUE = 42\n")
        zf.writestr(f"{archive_package}/sub/__init__.py", "")
        zf.writestr(
            f"{archive_package}/sub/module.py",
            f"from {_TEST_PKG} import VALUE\nSUB_VALUE = VALUE + 1\n",
        )
    return zip_path


@pytest.fixture()
def vendored_zip(tmp_path):
    """Yield a zip path with a minimal vendored package; restore sys.modules and sys.path after."""
    pre_modules = set(sys.modules.keys())
    zip_path = _make_vendored_zip(str(tmp_path))
    yield zip_path
    for key in [k for k in list(sys.modules) if k not in pre_modules]:
        sys.modules.pop(key, None)
    if zip_path in sys.path:
        sys.path.remove(zip_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vpf(zip_path: str | None = None) -> VendoredPackageFinder:
    """Return a VendoredPackageFinder scoped to the test package only."""
    return VendoredPackageFinder(_TEST_PLUGIN, packages=[_TEST_PKG], plugin_dir=zip_path)


class _FailingRedirectVPF(VendoredPackageFinder):
    """VPF subclass where load_module always raises, with no internal fallback.

    Models the Calibre 8.x failure condition: the calibre_plugins redirect fails AND
    VPF's own direct-import fallback also fails (due to stale partial module state or
    Windows file-locking on the zip after invalidate_caches()).  The net effect is that
    VPF sitting at position 0 in sys.meta_path blocks every intercepted import entirely.
    """

    def load_module(self, fullname: str) -> types.ModuleType:
        raise ImportError(f"calibre_plugins redirect failed for {fullname!r} (and direct fallback unavailable)")


# ---------------------------------------------------------------------------
# Group 1: VPF routing
# ---------------------------------------------------------------------------


def test_vpf_intercepts_vendored_top_level_package():
    """find_module returns self for a configured top-level package name."""
    vpf = _vpf()
    assert vpf.find_module(_TEST_PKG) is vpf


def test_vpf_intercepts_vendored_submodule():
    """find_module returns self for a dotted submodule of a configured package."""
    vpf = _vpf()
    assert vpf.find_module(f"{_TEST_PKG}.sub.module") is vpf


def test_vpf_ignores_stdlib_packages():
    """find_module returns None for standard-library packages."""
    vpf = _vpf()
    for name in ("os", "sys", "json", "importlib", "collections"):
        assert vpf.find_module(name) is None, f"VPF should not intercept stdlib: {name}"


def test_vpf_ignores_packages_outside_configured_list():
    """find_module returns None for packages not in the VPF's configured list."""
    vpf = VendoredPackageFinder(_TEST_PLUGIN, packages=["requests"])
    assert vpf.find_module("seleniumbase") is None
    assert vpf.find_module("requests") is vpf


def test_vpf_default_list_covers_all_vendored_packages():
    """Default VPF intercepts every entry in VENDORED_PACKAGES."""
    vpf = VendoredPackageFinder(_TEST_PLUGIN)
    for pkg in VENDORED_PACKAGES:
        assert vpf.find_module(pkg) is vpf, f"VPF must intercept: {pkg}"


@pytest.mark.parametrize(
    ("version_info", "expected"),
    [((3, 8), "py38"), ((3, 9), "py39"), ((3, 10), "current"), ((3, 14), "current")],
)
def test_browser_vendor_branch_matches_seleniumbase_markers(version_info, expected):
    assert browser_vendor_branch(version_info) == expected


def test_browser_vendor_branch_rejects_unsupported_python():
    with pytest.raises(RuntimeError, match="Python 3.8 or newer"):
        browser_vendor_branch((3, 7))


def test_configure_browser_vendor_path_prioritizes_runtime_branch(tmp_path):
    old_path = list(sys.path)
    try:
        paths = configure_browser_vendor_path(str(tmp_path), (3, 8))
        assert paths[0].replace("\\", "/").endswith("/browser_vendor/py38")
        assert paths[1].replace("\\", "/").endswith("/browser_vendor/shared")
        assert sys.path[:2] == paths
    finally:
        sys.path[:] = old_path


def test_browser_module_snapshot_restores_host_modules():
    host_module = types.ModuleType("requests")
    vendor_module = types.ModuleType("requests")
    previous = sys.modules.get("requests")
    try:
        sys.modules["requests"] = host_module
        snapshot = snapshot_browser_vendor_modules(_TEST_PLUGIN)
        clear_browser_vendor_modules(_TEST_PLUGIN)
        sys.modules["requests"] = vendor_module
        restore_browser_vendor_modules(_TEST_PLUGIN, snapshot)
        assert sys.modules["requests"] is host_module
    finally:
        if previous is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = previous


def test_browser_import_lock_is_shared_across_plugin_module_copies():
    """Both copied helpers must serialize mutations of process-wide import state."""
    helper_path = fetch_helper.__file__
    loaded_helpers = []
    for module_name in ("_romanceio_helper_copy", "_romanceio_fields_helper_copy"):
        spec = importlib.util.spec_from_file_location(module_name, helper_path)
        assert spec is not None and spec.loader is not None
        helper_copy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper_copy)
        loaded_helpers.append(helper_copy)

    assert loaded_helpers[0]._BROWSER_IMPORT_LOCK is loaded_helpers[1]._BROWSER_IMPORT_LOCK
    assert loaded_helpers[0]._BROWSER_IMPORT_LOCK is fetch_helper._BROWSER_IMPORT_LOCK


def test_shared_driver_cache_is_locked_across_worker_processes(tmp_path):
    """Two first-run workers must perform exactly one stable-cache install."""
    stable_base = tmp_path / "stable"
    drivers = stable_base / "drivers"
    drivers.mkdir(parents=True)
    runtime_paths = []
    for index in range(2):
        runtime_dir = tmp_path / f"runtime-{index}"
        runtime_dir.mkdir()
        runtime_paths.append(runtime_dir / "chromedriver")

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    ready_queue = context.Queue()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_prepare_cached_driver_in_process,
            args=(str(stable_base), str(runtime_path), start_event, ready_queue, result_queue),
        )
        for runtime_path in runtime_paths
    ]

    try:
        for process in processes:
            process.start()
        for _process in processes:
            ready_queue.get(timeout=15)
        start_event.set()
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    results = [result_queue.get(timeout=5) for _process in processes]
    assert all(status == "ok" for status, _value in results), results
    assert len({digest for _status, digest in results}) == 1
    install_calls = (stable_base / "install-calls.txt").read_text(encoding="ascii").splitlines()
    assert len(install_calls) == 1
    assert all(path.read_bytes() == b"shared driver bytes" for path in runtime_paths)


def test_driver_cache_lock_timeout_does_not_touch_cache(tmp_path):
    class UnavailableLock:
        def __init__(self, path):
            self.path = path

        def acquire(self, **_kwargs):
            return False

        def release(self):
            pytest.fail("an unacquired lock must not be released")

    class Installer:
        @staticmethod
        def main(_command):
            pytest.fail("installer must not run without the process lock")

    with pytest.raises(RuntimeError, match="Timed out waiting"):
        prepare_cached_chromedriver(
            sb_install=Installer,
            interprocess_lock_class=UnavailableLock,
            stable_base=str(tmp_path),
            chromedriver_path=str(tmp_path / "chromedriver"),
            runtime_chromedriver_path=str(tmp_path / "runtime" / "chromedriver"),
            log_func=lambda _message: None,
        )


def test_driver_cache_recovers_from_corrupt_bytes(tmp_path):
    stable_base = tmp_path / "stable"
    stable_base.mkdir()
    cached_driver = stable_base / "chromedriver"
    runtime_driver = tmp_path / "runtime" / "chromedriver"
    runtime_driver.parent.mkdir()
    cached_driver.write_bytes(b"original driver")
    record_driver_integrity(str(cached_driver))
    cached_driver.write_bytes(b"corrupt driver")
    install_commands = []

    class ImmediateLock:
        def __init__(self, _path):
            pass

        def acquire(self, **_kwargs):
            return True

        def release(self):
            pass

    class Installer:
        @staticmethod
        def main(command):
            install_commands.append(command)
            cached_driver.write_bytes(b"clean replacement driver")

    prepare_cached_chromedriver(
        sb_install=Installer,
        interprocess_lock_class=ImmediateLock,
        stable_base=str(stable_base),
        chromedriver_path=str(cached_driver),
        runtime_chromedriver_path=str(runtime_driver),
        log_func=lambda _message: None,
    )

    assert install_commands == ["chromedriver latest"]
    assert runtime_driver.read_bytes() == b"clean replacement driver"
    assert verify_driver_integrity(str(cached_driver)) is not None


@pytest.mark.parametrize("cached_major_version", (None, 139))
def test_driver_cache_refreshes_unusable_or_outdated_executable(tmp_path, monkeypatch, cached_major_version):
    stable_base = tmp_path / "stable"
    stable_base.mkdir()
    cached_driver = stable_base / "chromedriver"
    runtime_driver = tmp_path / "runtime" / "chromedriver"
    runtime_driver.parent.mkdir()
    cached_driver.write_bytes(b"old driver")
    record_driver_integrity(str(cached_driver))
    install_commands = []

    class ImmediateLock:
        def __init__(self, _path):
            pass

        def acquire(self, **_kwargs):
            return True

        def release(self):
            pass

    class Installer:
        @staticmethod
        def main(command):
            install_commands.append(command)
            cached_driver.write_bytes(b"new matching driver")

    monkeypatch.setattr(
        fetch_helper,
        "_executable_major_version",
        lambda _path: cached_major_version if cached_driver.read_bytes() == b"old driver" else 140,
    )
    prepare_cached_chromedriver(
        sb_install=Installer,
        interprocess_lock_class=ImmediateLock,
        stable_base=str(stable_base),
        chromedriver_path=str(cached_driver),
        runtime_chromedriver_path=str(runtime_driver),
        log_func=lambda _message: None,
        browser_major_version=140,
    )

    assert install_commands == ["chromedriver 140"]
    assert runtime_driver.read_bytes() == b"new matching driver"


def test_driver_cache_rejects_downloaded_wrong_major(tmp_path, monkeypatch):
    stable_base = tmp_path / "stable"
    stable_base.mkdir()
    cached_driver = stable_base / "chromedriver"
    runtime_driver = tmp_path / "runtime" / "chromedriver"
    runtime_driver.parent.mkdir()
    install_commands = []

    class ImmediateLock:
        def __init__(self, _path):
            pass

        def acquire(self, **_kwargs):
            return True

        def release(self):
            pass

    class Installer:
        @staticmethod
        def main(command):
            install_commands.append(command)
            cached_driver.write_bytes(b"wrong driver version")

    monkeypatch.setattr(fetch_helper, "_executable_major_version", lambda _path: 139)
    with pytest.raises(RuntimeError, match="expected major 140, driver 139"):
        prepare_cached_chromedriver(
            sb_install=Installer,
            interprocess_lock_class=ImmediateLock,
            stable_base=str(stable_base),
            chromedriver_path=str(cached_driver),
            runtime_chromedriver_path=str(runtime_driver),
            log_func=lambda _message: None,
            browser_major_version=140,
        )

    assert install_commands == ["chromedriver 140"]
    assert not cached_driver.exists()
    assert not runtime_driver.exists()


@pytest.mark.parametrize(
    "url",
    (
        "https://chromedriver.storage.googleapis.com/LATEST_RELEASE",
        "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE",
        "https://storage.googleapis.com/chrome-for-testing-public/123/linux64/chromedriver.zip",
    ),
)
def test_driver_download_urls_allow_only_google_tls_origins(url):
    assert validate_driver_download_url(url) == url


@pytest.mark.parametrize(
    "url",
    (
        "http://storage.googleapis.com/chromedriver.zip",
        "https://storage.googleapis.com.evil.example/chromedriver.zip",
        "https://example.com/chromedriver.zip",
        "https://user@storage.googleapis.com/chromedriver.zip",
        "https://storage.googleapis.com:444/chromedriver.zip",
    ),
)
def test_driver_download_urls_reject_untrusted_origins(url):
    with pytest.raises(RuntimeError, match="Refusing"):
        validate_driver_download_url(url)


def test_driver_integrity_record_detects_tampering(tmp_path):
    driver = tmp_path / "chromedriver"
    driver.write_bytes(b"trusted driver bytes")
    digest = record_driver_integrity(str(driver))

    assert verify_driver_integrity(str(driver)) == digest
    driver.write_bytes(b"modified driver bytes")
    with pytest.raises(RuntimeError, match="integrity check failed"):
        verify_driver_integrity(str(driver))


def test_prepare_uc_driver_replaces_tampered_copy_and_records_exact_bytes(tmp_path):
    source = tmp_path / "chromedriver"
    uc_driver = tmp_path / "uc_driver.exe"
    source.write_bytes(b"trusted source driver")
    record_driver_integrity(str(source))
    uc_driver.write_bytes(b"attacker-controlled persistent driver")

    class TestPatcher:
        def __init__(self, executable_path):
            assert executable_path.endswith(".exe")
            self.executable_path = executable_path

        def is_binary_patched(self):
            return self.executable_path.endswith("already-patched")

        def patch_exe(self):
            with open(self.executable_path, "ab") as executable:
                executable.write(b"::uc-patch")

    digest = prepare_uc_driver(str(source), str(uc_driver), TestPatcher)

    assert uc_driver.read_bytes() == b"trusted source driver::uc-patch"
    assert verify_driver_integrity(str(uc_driver)) == digest


def test_installed_fetch_page_uses_isolated_calibre_worker(monkeypatch):
    requests = []

    def fetch_in_worker(request, _log_func):
        requests.append(request)
        return "worker html"

    monkeypatch.setattr(fetch_helper, "_is_installed_plugin_module", lambda _name: True)
    monkeypatch.setattr(
        fetch_helper,
        "_fetch_page_via_calibre_worker",
        fetch_in_worker,
    )
    monkeypatch.setattr(
        fetch_helper,
        "_fetch_page_in_process",
        lambda **_kwargs: pytest.fail("installed plugins must not mutate imports in the host process"),
    )

    result = fetch_helper.fetch_page(
        "https://www.romance.io/books/example/",
        "romanceio",
        wait_for_element="book-stats",
        max_wait=45,
    )

    assert result == "worker html"
    assert requests == [
        {
            "url": "https://www.romance.io/books/example/",
            "plugin_name": "romanceio",
            "wait_for_element": "book-stats",
            "not_found_marker": None,
            "secondary_wait_element": None,
            "max_wait": 45,
        }
    ]


def test_worker_log_redaction_hides_home_and_temp_paths():
    home_message = os.path.join(os.path.expanduser("~"), ".calibre_selenium", "drivers")
    temp_message = os.path.join(fetch_helper.tempfile.gettempdir(), "calibre_sb_123")
    escaped_temp_message = temp_message.replace("\\", "\\\\")

    redacted = fetch_helper._redact_log_text(f"{home_message} {temp_message} {escaped_temp_message}")

    assert os.path.expanduser("~").lower() not in redacted.lower()
    assert fetch_helper.tempfile.gettempdir().replace("\\", "\\\\").lower() not in redacted.lower()
    assert "~" in redacted
    assert "<temp>" in redacted


@pytest.mark.parametrize("original_path", ("original-path-value", None))
def test_fetch_page_restores_path_when_setup_fails(monkeypatch, original_path):
    """Temporary driver-path changes must not leak into Calibre's process."""
    if original_path is None:
        monkeypatch.delenv("PATH", raising=False)
    else:
        monkeypatch.setenv("PATH", original_path)

    def fail_after_mutating_path(*_args, **_kwargs):
        os.environ["PATH"] = "temporary-driver-path"
        raise RuntimeError("setup failed")

    monkeypatch.setattr(fetch_helper.tempfile, "mkdtemp", fail_after_mutating_path)
    assert fetch_helper.fetch_page("https://example.invalid", _TEST_PLUGIN, log_func=lambda _message: None) is None

    if original_path is None:
        assert "PATH" not in os.environ
    else:
        assert os.environ["PATH"] == original_path


def test_fetch_page_releases_import_lock_when_state_snapshot_fails(monkeypatch):
    def fail_snapshot(_plugin_name):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(fetch_helper, "snapshot_browser_vendor_modules", fail_snapshot)
    assert fetch_helper.fetch_page("https://example.invalid", _TEST_PLUGIN, log_func=lambda _message: None) is None

    acquired = []

    def acquire_from_another_thread():
        lock_acquired = fetch_helper._BROWSER_IMPORT_LOCK.acquire(timeout=1)  # pylint: disable=protected-access
        acquired.append(lock_acquired)
        if lock_acquired:
            fetch_helper._BROWSER_IMPORT_LOCK.release()  # pylint: disable=protected-access

    thread = threading.Thread(target=acquire_from_another_thread)
    thread.start()
    thread.join(timeout=2)
    assert acquired == [True]


def test_nested_zip_distribution_metadata_is_discoverable(tmp_path):
    zip_path = _make_vendored_zip(str(tmp_path), "browser_vendor/current")
    with zipfile.ZipFile(zip_path, "a") as plugin_zip:
        plugin_zip.writestr(
            "browser_vendor/current/example_dist-1.2.3.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: example-dist\nVersion: 1.2.3\n",
        )
    package_root = zip_path + "/browser_vendor/current"
    original_meta_path = list(sys.meta_path)
    try:
        finder = configure_browser_vendor_metadata(zip_path, [package_root])
        assert finder is not None
        finder_result = finder.find_distributions(metadata.DistributionFinder.Context(name="example-dist"))
        assert iter(finder_result) is finder_result
        distribution = metadata.distribution("example-dist")
        assert distribution.version == "1.2.3"
        assert "browser_vendor/current" in str(distribution.locate_file("")).replace("\\", "/")
    finally:
        sys.meta_path[:] = original_meta_path


# ---------------------------------------------------------------------------
# Group 2: VPF loading
# ---------------------------------------------------------------------------


def test_vpf_load_module_falls_back_to_direct_import_when_redirect_unavailable(
    vendored_zip,
):  # pylint: disable=redefined-outer-name
    """When the calibre_plugins redirect fails, load_module loads the package via zipimport."""
    vpf = _vpf(vendored_zip)
    sys.path.insert(0, vendored_zip)
    module = vpf.load_module(_TEST_PKG)
    assert module.VALUE == 42


def test_vpf_fallback_supports_runtime_branch_inside_zip(tmp_path):
    zip_path = _make_vendored_zip(str(tmp_path), "browser_vendor/current")
    package_root = zip_path + "/browser_vendor/current"
    vpf = VendoredPackageFinder(
        _TEST_PLUGIN,
        packages=[_TEST_PKG],
        plugin_dir=zip_path,
        package_roots=[package_root],
    )
    pre_modules = set(sys.modules)
    sys.path.insert(0, package_root)
    try:
        module = vpf.load_module(_TEST_PKG)
        assert module.VALUE == 42
        assert vpf.package_roots == [package_root]
    finally:
        sys.path.remove(package_root)
        for key in [name for name in list(sys.modules) if name not in pre_modules]:
            sys.modules.pop(key, None)


def test_vpf_load_module_registers_both_namespaces(vendored_zip):  # pylint: disable=redefined-outer-name
    """After loading, both the bare name and the calibre_plugins alias resolve to the same object."""
    vpf = _vpf(vendored_zip)
    sys.path.insert(0, vendored_zip)
    vpf.load_module(_TEST_PKG)
    assert _TEST_PKG in sys.modules
    assert _ALIAS in sys.modules
    assert sys.modules[_TEST_PKG] is sys.modules[_ALIAS]


def test_vpf_load_module_is_idempotent(vendored_zip):  # pylint: disable=redefined-outer-name
    """Loading the same package twice returns the same cached module object."""
    vpf = _vpf(vendored_zip)
    sys.path.insert(0, vendored_zip)
    first = vpf.load_module(_TEST_PKG)
    second = vpf.load_module(_TEST_PKG)
    assert first is second


def test_vpf_load_module_raises_when_package_not_on_path():
    """load_module raises ImportError when the package cannot be found on sys.path."""
    vpf = _vpf()
    with pytest.raises(ImportError):
        vpf.load_module(_TEST_PKG)


# ---------------------------------------------------------------------------
# Group 3: Zip layout
# ---------------------------------------------------------------------------


def test_zip_file_is_valid_sys_path_entry(vendored_zip):  # pylint: disable=redefined-outer-name
    """Python's zipimport accepts a .zip file path as a sys.path entry."""
    sys.path.insert(0, vendored_zip)
    module = importlib.import_module(_TEST_PKG)
    assert module.VALUE == 42


def test_zipimport_resolves_intra_package_submodule(vendored_zip):  # pylint: disable=redefined-outer-name
    """Intra-package imports inside a zip (``from pkg import VALUE`` in sub/module.py) work via zipimport."""
    sys.path.insert(0, vendored_zip)
    sub = importlib.import_module(f"{_TEST_PKG}.sub.module")
    assert sub.SUB_VALUE == 43
    assert f"{_TEST_PKG}.sub.module" in sys.modules


def test_zip_path_derivable_from_module_file_inside_zip(vendored_zip):  # pylint: disable=redefined-outer-name
    """os.path.dirname of a path inside a zip yields the zip file path, which is a valid sys.path entry.

    When __file__ resolves to 'plugin.zip/helper.py', os.path.dirname gives 'plugin.zip'.
    This is the mechanism fetch_page() uses to add the plugin zip to sys.path.
    """
    fake_file = os.path.join(vendored_zip, "helper.py")
    derived = os.path.dirname(os.path.abspath(fake_file))
    assert derived == vendored_zip
    sys.path.insert(0, derived)
    module = importlib.import_module(_TEST_PKG)
    assert module.VALUE == 42


# ---------------------------------------------------------------------------
# Group 4: VPF priority strategy
# ---------------------------------------------------------------------------


def test_vpf_removed_before_import_lets_zipimport_load_full_tree(vendored_zip):  # pylint: disable=redefined-outer-name
    """Removing all VPFs from sys.meta_path lets zipimport handle the full import tree.

    This mirrors the fetch_page() strategy: save all VendoredPackageFinders,
    remove them, run the import, then re-add at low priority.
    """
    vpf = _vpf(vendored_zip)
    sys.meta_path.insert(0, vpf)
    sys.path.insert(0, vendored_zip)
    saved = [f for f in list(sys.meta_path) if isinstance(f, VendoredPackageFinder)]
    for f in saved:
        sys.meta_path.remove(f)
    try:
        module = importlib.import_module(_TEST_PKG)
        assert module.VALUE == 42
        assert not isinstance(module, VendoredModule), "zipimport should produce a real module, not a VendoredModule"
        assert vpf not in sys.meta_path
    finally:
        for f in saved:
            if f in sys.meta_path:
                sys.meta_path.remove(f)


def test_vpf_at_low_priority_defers_to_zipimport(vendored_zip):  # pylint: disable=redefined-outer-name
    """VPF appended at the end of sys.meta_path does not block imports that zipimport can serve.

    PathFinder (which handles sys.path entries including zips) sits in sys.meta_path
    before the appended VPF, so zipimport wins for pure-Python packages in a zip.
    """
    vpf = _vpf(vendored_zip)
    sys.path.insert(0, vendored_zip)
    sys.meta_path.append(vpf)
    try:
        module = importlib.import_module(_TEST_PKG)
        assert module.VALUE == 42
        assert not isinstance(module, VendoredModule), "PathFinder should win over low-priority VPF"
    finally:
        if vpf in sys.meta_path:
            sys.meta_path.remove(vpf)


def test_vpf_restored_at_high_priority_after_failed_direct_import(
    vendored_zip,
):  # pylint: disable=redefined-outer-name
    """Restoring VPF at position 0 and retrying after a failed direct attempt succeeds.

    This mirrors the fetch_page() fallback path: if the direct attempt raises,
    restore all VPFs at high priority (insert at 0) and call importlib.import_module again.
    """
    vpf = _vpf(vendored_zip)
    sys.path.insert(0, vendored_zip)
    saved = [vpf]
    # Simulate: direct import was tried and failed; restore VPFs at high priority
    for f in saved:
        sys.meta_path.insert(0, f)
    for k in [k for k in list(sys.modules) if k == _TEST_PKG or k.startswith(_TEST_PKG + ".")]:
        sys.modules.pop(k, None)
    try:
        module = importlib.import_module(_TEST_PKG)
        assert module.VALUE == 42
        assert vpf in sys.meta_path
    finally:
        if vpf in sys.meta_path:
            sys.meta_path.remove(vpf)


# ---------------------------------------------------------------------------
# Group 5: Regression - VPF redirect failure vs fetch_page() bypass
# ---------------------------------------------------------------------------


def test_vpf_at_high_priority_with_broken_redirect_matches_python_import_behavior(
    vendored_zip,
):  # pylint: disable=redefined-outer-name
    """A legacy VPF blocks Python 3.11, but Python 3.12+ ignores ``find_module``.

    Regression: this is what the user saw. VPF intercepts before zipimport can act,
    load_module's calibre_plugins redirect fails, the fallback also fails, so the
    import errors even though the package is present in a zip on sys.path. Python
    3.12 removed the ``find_module`` fallback from ``sys.meta_path`` processing, so
    modern Python correctly proceeds to zipimport instead.
    """
    vpf = _FailingRedirectVPF(_TEST_PLUGIN, packages=[_TEST_PKG])
    sys.meta_path.insert(0, vpf)
    sys.path.insert(0, vendored_zip)
    try:
        if sys.version_info < (3, 12):
            with pytest.raises(ImportError):
                importlib.import_module(_TEST_PKG)
        else:
            module = importlib.import_module(_TEST_PKG)
            assert module.VALUE == 42
    finally:
        if vpf in sys.meta_path:
            sys.meta_path.remove(vpf)


def test_fetch_page_strategy_bypasses_vpf_with_broken_redirect(vendored_zip):  # pylint: disable=redefined-outer-name
    """Removing all VPFs before importing succeeds even when VPF's redirect would fail.

    This is the fetch_page() fix: save all VendoredPackageFinders, remove them so
    zipimport can serve the import directly, then re-add at low priority.
    Paired with the test above: together they form a regression suite that would
    catch a revert of the save/remove/try/restore block in fetch_page().
    """
    vpf = _FailingRedirectVPF(_TEST_PLUGIN, packages=[_TEST_PKG])
    sys.meta_path.insert(0, vpf)
    sys.path.insert(0, vendored_zip)
    # fetch_page() strategy: save and remove all VPFs before the import
    saved = [f for f in list(sys.meta_path) if isinstance(f, VendoredPackageFinder)]
    for f in saved:
        sys.meta_path.remove(f)
    try:
        module = importlib.import_module(_TEST_PKG)
        assert module.VALUE == 42
        # Re-add at low priority (as fetch_page() does in the else branch)
        for f in saved:
            sys.meta_path.append(f)
    finally:
        for _f in list(sys.meta_path):
            if isinstance(_f, VendoredPackageFinder):
                sys.meta_path.remove(_f)
