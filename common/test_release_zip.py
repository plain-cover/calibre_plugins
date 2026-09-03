"""Audit built plugin ZIPs for portable, reproducible release contents."""

import argparse
import ast
import os
from pathlib import PurePosixPath
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build_utils import MAX_PLUGIN_ZIP_SIZE_BYTES

FORBIDDEN_PREFIXES = (
    "Xlib/",
    "lxml/",
    "psutil/",
)
FORBIDDEN_SUFFIXES = (".dylib", ".pyc", ".pyd", ".so")
FORBIDDEN_PATH_COMPONENTS = frozenset(
    {
        "__pycache__",
        "bin",
        "downloaded_files",
        "mcp_servers",
        "sbase",
    }
)
REQUIRED_ENTRIES = (
    "__init__.py",
    # Python 3.8/3.9 importlib.resources resolves this nested certifi resource
    # from the ZIP root. This data-only alias keeps Calibre 5 TLS imports usable.
    "certifi/cacert.pem",
    "browser_vendor/shared/seleniumbase/__init__.py",
    "browser_vendor/current/seleniumbase/__init__.py",
    "browser_vendor/py38/selenium/__init__.py",
    "browser_vendor/py39/selenium/__init__.py",
    "browser_vendor/current/selenium/__init__.py",
    "browser_vendor/current/urllib3/contrib/socks.py",
    "browser_vendor/shared/socks.py",
    "browser_vendor/shared/urllib3/contrib/socks.py",
)
REQUIRED_METADATA_PREFIXES = (
    "browser_vendor/current/trio-",
    "browser_vendor/current/seleniumbase-",
    "browser_vendor/py38/trio-",
    "browser_vendor/py39/trio-",
    "browser_vendor/shared/PySocks-",
    "browser_vendor/shared/trio_websocket-",
)
NON_RUNTIME_TOP_LEVEL_MODULES = {
    "build.py",
    "parse.py",
    "pdbp.py",
    "py.py",
    "pytest_ordering.py",
    "pytest_rerunfailures.py",
    "readline.py",
    "setuptools_behave.py",
    "socks.py",
    "sockshandler.py",
    "tabcompleter.py",
    "update_static_test_data.py",
}


def audit_release_zip(zip_path):
    """Raise AssertionError if a plugin ZIP contains host-specific build debris."""
    size_bytes = os.path.getsize(zip_path)
    size_mb = size_bytes / (1024 * 1024)
    assert (
        size_bytes < MAX_PLUGIN_ZIP_SIZE_BYTES
    ), f"Release ZIP must be smaller than 40 MB: {zip_path} is {size_mb:.2f} MB"

    with zipfile.ZipFile(zip_path) as plugin_zip:
        names = set(plugin_zip.namelist())

        # Parse each dependency branch with its oldest supported grammar. Shared
        # code and plugin modules must remain valid on Calibre 5's Python 3.8.
        incompatible_python = []
        for name in sorted(entry for entry in names if entry.endswith(".py")):
            try:
                source = plugin_zip.read(name).decode("utf-8-sig")
                if name.startswith("browser_vendor/current/"):
                    feature_version = (3, 10)
                elif name.startswith("browser_vendor/py39/"):
                    feature_version = (3, 9)
                else:
                    feature_version = (3, 8)
                ast.parse(source, filename=name, feature_version=feature_version)
            except (SyntaxError, UnicodeDecodeError) as error:
                incompatible_python.append(f"{name}: {error}")

    assert names, f"Release ZIP is empty: {zip_path}"
    assert not incompatible_python, f"Python 3.8-incompatible modules in {zip_path}: {incompatible_python[:10]}"

    python_folders = set()
    for name in names:
        if not name.endswith(".py"):
            continue
        folder = os.path.dirname(name).replace("\\", "/")
        while folder:
            python_folders.add(folder)
            folder = os.path.dirname(folder).replace("\\", "/")
    namespace_folders = [folder for folder in sorted(python_folders) if f"{folder}/__init__.py" not in names]
    assert (
        not namespace_folders
    ), f"Python directories without zipimport package markers in {zip_path}: {namespace_folders[:10]}"
    assert any(name.startswith("plugin-import-name-") for name in names), zip_path
    for required in REQUIRED_ENTRIES:
        assert required in names, f"Missing {required} from {zip_path}"
    for required_prefix in REQUIRED_METADATA_PREFIXES:
        assert any(
            name.startswith(required_prefix) and ".dist-info/" in name for name in names
        ), f"Missing runtime distribution metadata matching {required_prefix} from {zip_path}"

    unsafe = [name for name in names if name.startswith("/") or ".." in name.split("/")]
    assert not unsafe, f"Unsafe paths in {zip_path}: {unsafe[:10]}"

    forbidden_packages = [name for name in names if name.startswith(FORBIDDEN_PREFIXES)]
    assert not forbidden_packages, f"Host-native packages in {zip_path}: {forbidden_packages[:10]}"

    native_extensions = [name for name in names if name.lower().endswith(FORBIDDEN_SUFFIXES)]
    assert not native_extensions, f"Host-native extensions in {zip_path}: {native_extensions[:10]}"

    build_debris = [
        name
        for name in names
        if FORBIDDEN_PATH_COMPONENTS.intersection(PurePosixPath(name).parts[:-1])
        or name in NON_RUNTIME_TOP_LEVEL_MODULES
        or PurePosixPath(name).name == "sockshandler.py"
        or ("/" not in name and name.startswith("test_") and name.endswith(".py"))
    ]
    assert not build_debris, f"Build-only files in {zip_path}: {build_debris[:10]}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_paths", nargs="+")
    args = parser.parse_args()
    for zip_path in args.zip_paths:
        audit_release_zip(zip_path)
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f"PASS: portable release ZIP audit ({size_mb:.2f} MB): {os.path.abspath(zip_path)}")


if __name__ == "__main__":
    main()
