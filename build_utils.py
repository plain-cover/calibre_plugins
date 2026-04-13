"""
Shared utilities for building Calibre plugins.
These functions are used by individual plugin build.py scripts.
"""

import os
import re
import zipfile
from glob import glob


def add_folder_to_zip(my_zip_file, folder, exclude=None):
    """Recursively add a folder to a zip file, excluding specified patterns."""
    if exclude is None:
        exclude = []
    exclude_list = []
    for ex in exclude:
        exclude_list.extend(glob(folder + "/" + ex))
    for file in glob(folder + "/*"):
        if file in exclude_list:
            continue
        # Also check basename directly to handle path separator differences on Windows
        if os.path.basename(file) in exclude:
            continue
        if os.path.isfile(file):
            my_zip_file.write(file, file)
        elif os.path.isdir(file):
            add_folder_to_zip(my_zip_file, file, exclude=exclude)


def create_zip_file(filename, mode, files, exclude=None):
    """Create an uncompressed zip file for a Calibre plugin."""
    if exclude is None:
        exclude = []
    my_zip_file = zipfile.ZipFile(filename, mode, zipfile.ZIP_STORED)
    exclude_list = []
    for ex in exclude:
        exclude_list.extend(glob(ex))
    for file in files:
        if file in exclude_list:
            continue
        if os.path.isfile(file):
            _, base_filename = os.path.split(file)
            my_zip_file.write(file, base_filename)
        if os.path.isdir(file):
            add_folder_to_zip(my_zip_file, file, exclude=exclude)
    my_zip_file.close()
    return (1, filename)


def adjust_imports_if_exists(filename, plugin_name):
    """
    Adjust imports in a file to use the calibre_plugins namespace.

    Replace this:
        from common_menus import xxx
    with this:
        from calibre_plugins.<pluginName>.common_menus import xxx
    """
    if not os.path.exists(filename):
        return
    with open(filename, "r", encoding="utf-8") as file:
        content = file.read()
        new_content = content.replace("from common_", "from calibre_plugins." + plugin_name + ".common_")
        # Also adjust imports from calibre_plugins.common to calibre_plugins.<plugin_name>
        new_content = new_content.replace("from calibre_plugins.common.", "from calibre_plugins." + plugin_name + ".")
    with open(filename, "w", encoding="utf-8") as file:
        file.write(new_content)


def copy_common_files():
    """Copy common files from ../common folder to current plugin folder."""
    common_folder = os.path.join(os.path.dirname(os.getcwd()), "common")
    if not os.path.exists(common_folder):
        return

    for filename in os.listdir(common_folder):
        # Skip __init__.py - it's only for mypy, not for copying to plugins
        if filename.endswith(".py") and filename != "__init__.py":
            src_path = os.path.join(common_folder, filename)
            dst_path = os.path.join(os.getcwd(), filename)
            with open(src_path, "r", encoding="utf-8") as src_file:
                content = src_file.read()
            with open(dst_path, "w", encoding="utf-8") as dst_file:
                dst_file.write(content)
            print(f"Copied {filename} from common folder")


def copy_static_test_data():
    """Copy static test data directory from ../common to current plugin folder."""
    import shutil

    common_folder = os.path.join(os.path.dirname(os.getcwd()), "common")
    static_test_data_src = os.path.join(common_folder, "common_romanceio_static_test_data")
    static_test_data_dst = os.path.join(os.getcwd(), "common_romanceio_static_test_data")

    if not os.path.exists(static_test_data_src):
        print(f"WARNING: Static test data directory not found at {static_test_data_src}")
        return

    # Remove existing directory if it exists
    if os.path.exists(static_test_data_dst):
        shutil.rmtree(static_test_data_dst)

    # Copy the entire directory
    shutil.copytree(static_test_data_src, static_test_data_dst)
    print("Copied static test data directory from common folder")


def get_plugin_subfolders(exclude_folders=None):
    """Get list of subfolders to include in the plugin, excluding specified folders."""
    if exclude_folders is None:
        exclude_folders = {
            "downloaded_files",  # SeleniumBase runtime downloads
            "__pycache__",  # Python bytecode cache
            "test_data",  # Test HTML files
            "common_romanceio_static_test_data",  # Test fixtures, not needed at runtime
            "bin",  # CLI executables (sbase, seleniumbase, etc.), not used by plugin
        }

    cwd = os.getcwd()
    folders = []
    for subfolder in os.listdir(cwd):
        subfolder_path = os.path.join(cwd, subfolder)
        if os.path.isdir(subfolder_path):
            # Filter out our special development folders like .build and .tx
            # Also filter out pip metadata directories (not needed at runtime)
            if (
                not subfolder.startswith(".")
                and subfolder not in exclude_folders
                and not subfolder.endswith(".dist-info")
            ):
                folders.append(subfolder)
    return folders


def read_plugin_name():
    """Read plugin name and version from __init__.py."""
    init_file = os.path.join(os.getcwd(), "__init__.py")
    if not os.path.exists(init_file):
        print("ERROR: No __init__.py file found for this plugin")
        raise FileNotFoundError(init_file)

    zip_file_name = None
    version = "unknown"
    with open(init_file, "r", encoding="utf-8") as file:
        content = file.read()
        name_matches = re.findall(r"\s+name\s*=\s*['\"]([^'\"]*)['\"]", content)
        if name_matches:
            zip_file_name = name_matches[0] + ".zip"
        else:
            raise RuntimeError("Could not find plugin name in __init__.py")
        version_matches = re.findall(r"\s+version\s*=\s*\(([^\)]*)\)", content)
        if version_matches:
            version = version_matches[0].replace(",", ".").replace(" ", "")

    print(f"Plugin v{version} will be zipped to: '{zip_file_name}'")
    return zip_file_name


def adjust_common_imports_for_plugin(plugin_specific_files=None):
    """
    Adjust imports for common files and optional plugin-specific files.

    Args:
        plugin_specific_files: List of plugin-specific files that import from common (e.g., ["worker.py", "jobs.py"])
    """
    if plugin_specific_files is None:
        plugin_specific_files = []

    plugin_name = os.path.split(os.getcwd())[1]

    # Adjust common files that have interdependencies
    common_files = [
        "common_compatibility.py",
        "common_dialogs.py",
        "common_icons.py",
        "common_menus.py",
        "common_romanceio_search.py",
        "common_widgets.py",
        "common_romanceio_fetch_helper.py",
        "common_romanceio_json_api.py",
        "common_romanceio_search_orchestrator.py",
        "common_romanceio_validation.py",
        "common_romanceio_test_utils.py",
        "common_romanceio_static_test_data.py",
        "common_romanceio_tag_mappings.py",
        "test_data.py",
        "test_json_search_matching.py",
        "test_tag_slug_conversion.py",
        "test_html_sanitizer.py",
    ]

    for filename in common_files:
        adjust_imports_if_exists(filename, plugin_name)

    # Also adjust imports in plugin-specific files that import from common
    for filename in plugin_specific_files:
        adjust_imports_if_exists(filename, plugin_name)


def build_plugin(adjust_imports_func):
    """
    Main build function that can be called from plugin build.py files.

    Args:
        adjust_imports_func: Function to call for adjusting imports specific to this plugin
    """
    zip_file_name = read_plugin_name()
    copy_static_test_data()
    copy_common_files()
    adjust_imports_func()

    files = get_plugin_subfolders()
    # Exclude driver binaries but keep drivers/__init__.py so seleniumbase can
    # import the drivers subpackage (browser_launcher.py does: from seleniumbase import drivers)
    exclude = [
        "*.pyc",
        "*~",
        "*.xcf",
        "build.py",
        "*.po",
        "*.pot",
        "uc_driver",
        "uc_driver.exe",
        "chromedriver",
        "chromedriver.exe",
        "geckodriver",
        "geckodriver.exe",
        "msedgedriver",
        "msedgedriver.exe",
        "IEDriverServer.exe",
        "headless_ie_selenium.exe",
        "undetected_chromedriver",
        "undetected_chromedriver.exe",
    ]
    files.extend(glob("*.py"))
    files.extend(glob("*.md"))
    files.extend(glob("*.html"))
    files.extend(glob("*.cmd"))
    files.extend(glob("plugin-import-name-*.txt"))

    create_zip_file(zip_file_name, "w", files, exclude=exclude)

    size_mb = os.path.getsize(zip_file_name) / (1024 * 1024)
    print(f"Plugin zip size: {size_mb:.1f} MB")


def pre_build_setup():
    """Run pre-build tasks before creating the plugin zip.

    Checks if the tag mappings file is more than 30 days old and updates it if needed.
    Safe to call from any plugin's build.py - uses the root-level update_tag_mappings module.
    """
    from datetime import datetime

    tag_mappings_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common", "common_romanceio_tag_mappings.py"
    )

    should_update = False
    try:
        with open(tag_mappings_file, "r", encoding="utf-8") as f:
            content = f.read()
            match = re.search(r"# Last tag mapping update: (\d{4}-\d{2}-\d{2})", content)
            if match:
                last_update = datetime.strptime(match.group(1), "%Y-%m-%d")
                days_old = (datetime.now() - last_update).days
                if days_old > 30:
                    should_update = True
                    print(f"\n[build] Tag mappings are {days_old} days old, updating...")
                else:
                    print(f"[build] Tag mappings are current ({days_old} days old)")
            else:
                should_update = True
                print("\n[build] No last update date found, updating tag mappings...")
    except OSError:
        pass

    if should_update:
        print("=" * 60)
        print("Pre-build: Updating tag mappings from Romance.io")
        print("=" * 60)

        try:
            from update_tag_mappings import update_tag_mappings

            success = update_tag_mappings()
            if not success:
                print("Warning: Tag mapping update failed, but continuing with build")
        except (ImportError, OSError, RuntimeError) as e:
            print(f"Warning: Could not update tag mappings: {e}")
            print("Continuing with build using existing mappings...")

        print("=" * 60)
        print()
