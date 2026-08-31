"""Import the browser stack from a built ZIP inside Calibre's Python."""

import argparse
import importlib
from importlib import metadata
import os
import sys


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
    args = parser.parse_args()
    zip_path = os.path.abspath(args.zip_path)
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
    assert expected_seleniumbase in seleniumbase_origin, seleniumbase_origin
    assert expected_runtime in selenium_origin, selenium_origin
    for dependency in (filelock, requests, typing_extensions, websockets):
        dependency_origin = _origin(dependency).replace("\\", "/")
        assert (
            expected_runtime in dependency_origin
        ), f"{dependency.__name__} used the wrong runtime branch: {dependency_origin}"
    expected_urllib3 = expected_runtime if expected_branch == "current" else "browser_vendor/shared"
    assert expected_urllib3 in _origin(urllib3).replace("\\", "/"), _origin(urllib3)
    assert socks_support.SOCKSProxyManager is not None

    distribution_expectations = {
        "seleniumbase": expected_seleniumbase.rsplit("/seleniumbase", 1)[0],
        "trio": expected_runtime,
        "trio-websocket": "browser_vendor/shared",
        "PySocks": "browser_vendor/shared",
    }
    for distribution_name, expected_path in distribution_expectations.items():
        distribution_path = str(metadata.distribution(distribution_name).locate_file("")).replace("\\", "/")
        assert (
            expected_path in distribution_path
        ), f"{distribution_name} metadata used the wrong runtime branch: {distribution_path}"
    if not args.pure_python_only:
        assert not _origin(lxml).startswith(zip_path), f"lxml must come from Calibre: {_origin(lxml)}"
        assert not _origin(psutil).startswith(zip_path), f"psutil must come from Calibre: {_origin(psutil)}"

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
