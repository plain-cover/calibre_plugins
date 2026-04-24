"""Tests for VendoredPackageFinder import routing and the direct-zipimport strategy.

VendoredPackageFinder (VPF) sits in sys.meta_path and redirects bare package
imports (e.g. ``import seleniumbase``) to the calibre_plugins-namespaced copy
(e.g. ``calibre_plugins.romanceio.seleniumbase``) so all plugins share the same
vendored library.  When that redirect fails, VPF falls back to loading the package
directly via zipimport.

fetch_page() uses a complementary strategy: it removes all VPFs from sys.meta_path
before importing seleniumbase, then re-adds them at low priority after.  This lets
zipimport handle the full import tree without VPF intercepting every sub-import,
while keeping VPF available for C extensions (e.g. lxml.etree) that cannot be
loaded from a zip.

Test groups:
  1. VPF routing   - find_module intercept/pass-through logic.
  2. VPF loading   - calibre_plugins redirect and direct-zipimport fallback.
  3. Zip layout    - vendored packages load from a zip on sys.path.
  4. Priority strategy - removing/re-adding VPF around a pure-Python import.
  5. Regression    - VPF with broken redirect blocks import; fetch_page() strategy bypasses it.
"""

import importlib
import importlib.abc
import os
import sys
import types
import zipfile

import pytest

from common.common_romanceio_fetch_helper import (
    VENDORED_PACKAGES,
    VendoredModule,
    VendoredPackageFinder,
)

_TEST_PKG = "_test_vendored_pkg"
_TEST_PLUGIN = "_test_plugin"
_ALIAS = f"calibre_plugins.{_TEST_PLUGIN}.{_TEST_PKG}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vendored_zip(directory: str) -> str:
    """Return the path of a zip containing a minimal two-level vendored package.

    plugin.zip/
        _test_vendored_pkg/__init__.py       VALUE = 42
        _test_vendored_pkg/sub/__init__.py
        _test_vendored_pkg/sub/module.py     SUB_VALUE = VALUE + 1 (intra-package import)
    """
    zip_path = os.path.join(directory, "plugin.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{_TEST_PKG}/__init__.py", "VALUE = 42\n")
        zf.writestr(f"{_TEST_PKG}/sub/__init__.py", "")
        zf.writestr(
            f"{_TEST_PKG}/sub/module.py",
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


def test_vpf_restored_at_high_priority_after_failed_direct_import(vendored_zip):  # pylint: disable=redefined-outer-name
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


def test_vpf_at_high_priority_with_broken_redirect_blocks_import(vendored_zip):  # pylint: disable=redefined-outer-name
    """VPF at position 0 with a broken redirect (and no internal fallback) raises ImportError.

    Regression: this is what the user saw. VPF intercepts before zipimport can act,
    load_module's calibre_plugins redirect fails, the fallback also fails, so the
    import errors even though the package is present in a zip on sys.path.
    """
    vpf = _FailingRedirectVPF(_TEST_PLUGIN, packages=[_TEST_PKG])
    sys.meta_path.insert(0, vpf)
    sys.path.insert(0, vendored_zip)
    try:
        with pytest.raises(ImportError):
            importlib.import_module(_TEST_PKG)
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
