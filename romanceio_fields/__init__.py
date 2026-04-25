"""
A Calibre plugin to download custom metadata from Romance.io including tags,
steam ratings, star ratings, number of ratings, and tags.
"""

__license__ = "GPL v3"

from calibre.customize import InterfaceActionBase

# Plugin metadata constants - keep these in sync with the values in the ActionRomanceIOFields class below
PLUGIN_NAME = "Romance.io Fields"
PLUGIN_DESCRIPTION = "Download custom metadata from Romance.io like steam rating and tags"
PLUGIN_AUTHOR = "plain-cover"
PLUGIN_VERSION = (1, 1, 1)
PLUGIN_MINIMUM_CALIBRE_VERSION = (5, 0, 0)
PLUGIN_ACTUAL_PLUGIN = "calibre_plugins.romanceio_fields.action:RomanceIOFieldsAction"


class ActionRomanceIOFields(InterfaceActionBase):  # type: ignore[misc]  # pylint: disable=abstract-method
    """
    This class is a simple wrapper that provides information about the actual
    plugin class. The actual interface plugin class is called InterfacePlugin
    and is defined in the ui.py file, as specified in the actual_plugin field
    below.

    The reason for having two classes is that it allows the command line
    calibre utilities to run without needing to load the GUI libraries.
    """

    name = "Romance.io Fields"  # Must match PLUGIN_NAME
    description = "Download custom metadata from Romance.io like steam rating and tags"  # Must match PLUGIN_DESCRIPTION
    supported_platforms = ["windows", "osx", "linux"]
    author = "plain-cover"  # Must match PLUGIN_AUTHOR
    version = (1, 1, 1)  # Must match PLUGIN_VERSION
    minimum_calibre_version = (5, 0, 0)  # Must match PLUGIN_MINIMUM_CALIBRE_VERSION

    #: This field defines the GUI plugin class that contains all the code
    #: that actually does something. Its format is module_path:class_name
    #: The specified class must be defined in the specified module.
    # Must match PLUGIN_ACTUAL_PLUGIN:
    actual_plugin: str = "calibre_plugins.romanceio_fields.action:RomanceIOFieldsAction"  # type: ignore

    def is_customizable(self):
        """
        This method must return True to enable customization via
        Preferences->Plugins
        """
        return True

    def config_widget(self):
        """
        Implement this method and :meth:`save_settings` in your plugin to
        use a custom configuration dialog.

        This method, if implemented, must return a QWidget. The widget can have
        an optional method validate() that takes no arguments and is called
        immediately after the user clicks OK. Changes are applied if and only
        if the method returns True.

        If for some reason you cannot perform the configuration at this time,
        return a tuple of two strings (message, details), these will be
        displayed as a warning dialog to the user and the process will be
        aborted.

        The base class implementation of this method raises NotImplementedError
        so by default no user configuration is possible.
        """
        if self.actual_plugin_:
            from .config import ConfigWidget

            return ConfigWidget(self.actual_plugin_)

        raise NotImplementedError("No configuration widget implemented")

    def save_settings(self, config_widget):
        """
        Save the settings specified by the user with config_widget.

        :param config_widget: The widget returned by :meth:`config_widget`.
        """
        config_widget.save_settings()


if __name__ == "__main__":
    # To run these tests use:
    # calibre-debug -e __init__.py
    import os
    import sys

    # Add parent directory to path to import shared test utilities
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from common.test_data import verify_and_print_plugin

    # Simple smoke test - verify plugin can be instantiated
    plugin_path = os.path.abspath(__file__)
    plugin = verify_and_print_plugin(
        ActionRomanceIOFields,
        plugin_path,
        PLUGIN_NAME,
        PLUGIN_VERSION,
        PLUGIN_AUTHOR,
        PLUGIN_MINIMUM_CALIBRE_VERSION,
        additional_checks={"actual_plugin": PLUGIN_ACTUAL_PLUGIN},
        additional_info={"Customizable": True},
    )

    assert plugin.is_customizable() is True, "Expected plugin to be customizable"
