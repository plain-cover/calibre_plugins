import os
from typing import cast, Any
from calibre.constants import iswindows, numeric_version as calibre_version
from calibre.utils.config import config_dir

try:
    from qt.core import QIcon, QPixmap
except ImportError:
    from PyQt5.Qt import QIcon, QPixmap

# Plugin state for icon resource management
_plugin_state: dict[str, Any] = {"name": None, "resources": {}}


def set_plugin_icon_resources(name, resources):
    """Register plugin icon resources for Romance.io plugins.

    Establishes the plugin name and icon resources that will be shared between
    the InterfaceAction class and ConfigWidget for the customization dialog.
    """
    _plugin_state["name"] = name
    _plugin_state["resources"] = resources


def get_icon_6_2_plus(icon_name):
    """Load icon for calibre 6.2+ using modern API.

    Searches for icons in order:
    1. Calibre's image cache
    2. resources/images directory
    3. Icon theme
    4. Plugin ZIP resources
    """
    if icon_name:
        # First try to load the icon using calibre's modern icon API
        icon = QIcon.ic(icon_name)
        if icon and not icon.isNull():
            return icon
        # If that didn't work, try without the images/ prefix
        icon = QIcon.ic(icon_name.replace("images/", ""))
        if icon and not icon.isNull():
            return icon
        # Fall back to loading from pixmap (plugin ZIP resources)
        pixmap = get_pixmap(icon_name)
        if pixmap is not None:
            return QIcon(pixmap)
    return QIcon()


def get_icon_old(icon_name):
    """Load icon for older calibre versions.

    Retrieves icons from plugin ZIP or calibre's cache as fallback.
    """
    from calibre.gui2 import I

    if icon_name:
        pixmap = get_pixmap(icon_name)
        if pixmap is None:
            return QIcon(I(icon_name))
        return QIcon(pixmap)
    return QIcon()


def get_pixmap(icon_name):
    """Load a QPixmap for Romance.io plugin icons.

    Plugin icons must be prefixed with 'images/'. Supports user skinning
    by checking the calibre resources directory first.
    """
    from calibre.gui2 import I

    if not icon_name.startswith("images/"):
        # This is a calibre builtin icon
        pixmap = QPixmap()
        pixmap.load(I(icon_name))
        return pixmap

    # Support user skinning via local resources folder
    if _plugin_state["name"]:
        local_images_dir = get_local_images_dir(_plugin_state["name"])
        local_image_path = os.path.join(local_images_dir, icon_name.replace("images/", ""))
        if os.path.exists(local_image_path):
            pixmap = QPixmap()
            pixmap.load(local_image_path)
            return pixmap

    if icon_name in _plugin_state["resources"]:
        pixmap = QPixmap()
        pixmap.loadFromData(_plugin_state["resources"][icon_name])
        return pixmap
    return None


def get_local_images_dir(subfolder=None):
    """
    Returns a path to the user's local resources/images folder
    If a subfolder name parameter is specified, appends this to the path
    """
    images_dir = os.path.join(config_dir, "resources/images")
    if subfolder:
        images_dir = os.path.join(images_dir, subfolder)
    if iswindows:
        images_dir = os.path.normpath(images_dir)
    return images_dir


if cast(tuple, calibre_version) >= (6, 2, 0):
    get_icon = get_icon_6_2_plus
else:
    get_icon = get_icon_old
