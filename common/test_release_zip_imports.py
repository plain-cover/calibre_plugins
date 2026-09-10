"""Audit shared runtime and browser dependency imports from a release ZIP."""

import argparse
import importlib
from importlib import metadata
import os
import sys
import types


def _origin(module):
    return str(getattr(module, "__file__", "") or getattr(getattr(module, "__spec__", None), "origin", ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pure-python-only",
        action="store_true",
        help="Skip Calibre-provided native modules when running under a standalone compatibility interpreter",
    )
    parser.add_argument("zip_path")
    parser.add_argument(
        "--skip-qt", action="store_true", help="Audit the full Chrome stack in standalone Python without Qt"
    )
    args = parser.parse_args()
    zip_path = os.path.abspath(args.zip_path)
    # A package path permits the same relative imports as Calibre's loader,
    # without requiring installation or executing the plugin's GUI entry point.
    package_name = "_release_probe"
    package = types.ModuleType(package_name)
    package.__path__ = [zip_path]
    sys.modules[package_name] = package
    for name in (
        "common_romanceio_fetch_helper",
        "common_romanceio_session",
        "common_romanceio_json_api",
        "common_romanceio_webengine",
        "common_romanceio_search_orchestrator",
    ):
        module = importlib.import_module(f"{package_name}.{name}")
        if not (module.__file__):
            raise AssertionError(name)
        origin = os.path.normcase(os.path.abspath(module.__file__))
        if not (origin.startswith(os.path.normcase(zip_path) + os.sep)):
            raise AssertionError(origin)
    if any(name == "seleniumbase" or name.startswith("seleniumbase.") for name in sys.modules):
        raise AssertionError("Shared runtime imports unexpectedly loaded SeleniumBase")
    print("PASS: shared runtime imports without loading Selenium")
    if not args.pure_python_only and not args.skip_qt:
        try:
            from qt.webengine import QWebEnginePage, QWebEngineProfile
        except ImportError:
            from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile
        if not (QWebEnginePage and QWebEngineProfile):
            raise AssertionError("Smoke check failed: QWebEnginePage and QWebEngineProfile")
    sys.path.insert(0, zip_path)

    helper = importlib.import_module("common_romanceio_fetch_helper")
    vendor_paths = helper.configure_browser_vendor_path(zip_path)
    helper.configure_browser_vendor_metadata(zip_path, vendor_paths)
    expected_branch = helper.browser_vendor_branch()
    helper.clear_browser_vendor_modules("release_zip_import_test")

    # These are the modules the production Chrome path imports before creating
    # a driver. Native packages must come from Calibre, while pure-Python
    # browser dependencies must come from the release ZIP.
    seleniumbase = importlib.import_module("seleniumbase")
    selenium = importlib.import_module("selenium")
    importlib.import_module("seleniumbase.fixtures.constants")
    importlib.import_module("seleniumbase.console_scripts.sb_install")
    importlib.import_module("seleniumbase.core.download_helper")
    importlib.import_module("seleniumbase.undetected.patcher")
    if not args.pure_python_only:
        importlib.import_module("seleniumbase.core.browser_launcher")
        importlib.import_module("seleniumbase.plugins.driver_manager")

    filelock = importlib.import_module("filelock")
    requests = importlib.import_module("requests")
    typing_extensions = importlib.import_module("typing_extensions")
    urllib3 = importlib.import_module("urllib3")
    websockets = importlib.import_module("websockets")
    socks_support = importlib.import_module("urllib3.contrib.socks")
    lxml = importlib.import_module("lxml") if not args.pure_python_only else None
    psutil = importlib.import_module("psutil") if not args.pure_python_only else None

    expected_runtime = f"browser_vendor/{expected_branch}"
    expected_seleniumbase = (
        f"{expected_runtime}/seleniumbase" if expected_branch == "current" else "browser_vendor/shared/seleniumbase"
    )
    seleniumbase_origin = _origin(seleniumbase).replace("\\", "/")
    selenium_origin = _origin(selenium).replace("\\", "/")
    filelock_origin = _origin(filelock).replace("\\", "/")
    if not (expected_seleniumbase in seleniumbase_origin):
        raise AssertionError(seleniumbase_origin)
    if not (expected_runtime in selenium_origin):
        raise AssertionError(selenium_origin)
    for dependency in (filelock, requests, typing_extensions, websockets):
        dependency_origin = _origin(dependency).replace("\\", "/")
        if dependency is typing_extensions and type(dependency.__loader__).__module__ == "bypy_importer":
            # Calibre's frozen importer precedes ZIP paths for this module.
            # The browser-stack imports above exercise its required APIs.
            print(f"Using Calibre's frozen typing_extensions: {dependency_origin}")
            continue
        if not (expected_runtime in dependency_origin):
            raise AssertionError(f"{dependency.__name__} used the wrong runtime branch: {dependency_origin}")
    expected_urllib3 = expected_runtime if expected_branch == "current" else "browser_vendor/shared"
    if not (expected_urllib3 in _origin(urllib3).replace("\\", "/")):
        raise AssertionError(_origin(urllib3))
    if not (socks_support.SOCKSProxyManager is not None):
        raise AssertionError("Smoke check failed: socks_support.SOCKSProxyManager is not None")

    distribution_expectations = {
        "seleniumbase": expected_seleniumbase.rsplit("/seleniumbase", 1)[0],
        "trio": expected_runtime,
        "trio-websocket": "browser_vendor/shared",
        "PySocks": "browser_vendor/shared",
    }
    for distribution_name, expected_path in distribution_expectations.items():
        distribution_path = str(metadata.distribution(distribution_name).locate_file("")).replace("\\", "/")
        if not (expected_path in distribution_path):
            raise AssertionError(f"{distribution_name} metadata used the wrong runtime branch: {distribution_path}")
    if not args.pure_python_only:
        if _origin(lxml).startswith(zip_path):
            raise AssertionError(f"lxml must come from Calibre: {_origin(lxml)}")
        if _origin(psutil).startswith(zip_path):
            raise AssertionError(f"psutil must come from Calibre: {_origin(psutil)}")

    print(f"PASS: SeleniumBase imports from release ZIP: {zip_path}")
    print(f"  vendor paths: {vendor_paths}")
    print(f"  seleniumbase: {_origin(seleniumbase)}")
    print(f"  selenium: {_origin(selenium)}")
    print(f"  filelock: {_origin(filelock)}")
    if not args.pure_python_only:
        print(f"  lxml: {_origin(lxml)}")
        print(f"  psutil: {_origin(psutil)}")


if __name__ == "__main__":
    main()
