"""
Creates an uncompressed zip file for the plugin.
Plugin zips are uncompressed so to not negatively impact calibre load times.
"""

import os
import sys

# Add parent directory to path to import build_utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build_utils import adjust_common_imports_for_plugin, build_plugin, pre_build_setup


if __name__ == "__main__":
    pre_build_setup()
    build_plugin(lambda: adjust_common_imports_for_plugin(["jobs.py"]))
