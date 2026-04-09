"""
Allow the user to configure the plugin.
"""

import copy
from typing import Any, Dict, List

from six import text_type as unicode

# pylint: disable=duplicate-code  # Standard Calibre plugin import pattern
try:
    from qt.core import (
        QWidget,
        QGridLayout,
        QLabel,
        QPushButton,
        QUrl,  # type: ignore # pylint: disable=unused-import
        QGroupBox,
        QVBoxLayout,
        QCheckBox,
        QLineEdit,
        QHBoxLayout,
    )
except ImportError:
    from PyQt5.QtCore import QUrl
    from PyQt5.QtWidgets import (
        QWidget,
        QGridLayout,
        QLabel,
        QPushButton,
        QGroupBox,
        QVBoxLayout,
        QCheckBox,
        QLineEdit,
        QHBoxLayout,
    )

from calibre.gui2 import open_url
from calibre.utils.config import JSONConfig

from .common_dialogs import KeyboardConfigDialog, PrefsViewerDialog  # pylint: disable=import-error
from .common_widgets import CustomColumnComboBox  # pylint: disable=import-error

# Pull in translation files for _() strings
try:
    load_translations()  # type: ignore[name-defined]  # pylint: disable=undefined-variable
except NameError:
    pass  # load_translations() added in calibre 1.9
# pylint: enable=duplicate-code

ID_NAME = "romanceio"

TAG_DELIMITER = ","

PREFS_NAMESPACE = "RomanceIOFieldsPlugin"
PREFS_KEY_SETTINGS = "settings"

KEY_STEAM_CUSTOM_COLUMN = "customColumnSteam"
KEY_TAGS_CUSTOM_COLUMN = "customColumnRomanceTags"
KEY_STAR_RATING_CUSTOM_COLUMN = "customColumnStarRating"
KEY_RATING_COUNT_CUSTOM_COLUMN = "customColumnRatingCount"

STORE_NAME = "Options"
KEY_MAX_TAGS = "maxRomanceTags"
KEY_OVERWRITE_EXISTING = "overwriteExisting"
KEY_ASK_FOR_CONFIRMATION = "askForConfirmation"
KEY_PREFER_HTML = "preferHtmlParsing"

FIELD_STEAM_RATING = "SteamRating"
FIELD_ROMANCE_TAGS = "RomanceTags"
FIELD_STAR_RATING = "StarRating"
FIELD_RATING_COUNT = "RatingCount"
ALL_FIELDS: Dict[str, str] = {
    FIELD_STEAM_RATING: KEY_STEAM_CUSTOM_COLUMN,
    FIELD_ROMANCE_TAGS: KEY_TAGS_CUSTOM_COLUMN,
    FIELD_STAR_RATING: KEY_STAR_RATING_CUSTOM_COLUMN,
    FIELD_RATING_COUNT: KEY_RATING_COUNT_CUSTOM_COLUMN,
}

DEFAULT_STORE_VALUES = {
    KEY_ASK_FOR_CONFIRMATION: False,
    KEY_OVERWRITE_EXISTING: True,
    KEY_PREFER_HTML: False,
}
DEFAULT_LIBRARY_VALUES: Dict[str, Any] = {
    KEY_MAX_TAGS: 50,
    KEY_STEAM_CUSTOM_COLUMN: "",
    KEY_TAGS_CUSTOM_COLUMN: "",
    KEY_STAR_RATING_CUSTOM_COLUMN: "",
    KEY_RATING_COUNT_CUSTOM_COLUMN: "",
}

PLUGIN_ICONS: List[str] = [
    "images/logo.png",
    "images/download.png",
]

KEY_SCHEMA_VERSION = "SchemaVersion"
DEFAULT_SCHEMA_VERSION = 1.61


# This is where all preferences for this plugin will be stored
plugin_prefs = JSONConfig("plugins/RomanceIOFields")

plugin_prefs.defaults[STORE_NAME] = DEFAULT_STORE_VALUES


def migrate_library_config_if_required(db, library_config):
    schema_version = library_config.get(KEY_SCHEMA_VERSION, 0)
    if schema_version == DEFAULT_SCHEMA_VERSION:
        return
    # We have changes to be made - mark schema as updated
    library_config[KEY_SCHEMA_VERSION] = DEFAULT_SCHEMA_VERSION

    # Any migration code in future will exist in here.
    if schema_version < 1.61:
        if "customColumn" in library_config:
            library_config[KEY_STEAM_CUSTOM_COLUMN] = library_config["customColumn"]
            del library_config["customColumn"]

    set_library_config(db, library_config)


def get_library_config(db):
    library_id = db.library_id
    library_config = None
    # Check whether this is a configuration needing to be migrated from json into database
    if "libraries" in plugin_prefs:
        libraries = plugin_prefs["libraries"]
        if library_id in libraries:
            # We will migrate this below
            library_config = libraries[library_id]
            # Cleanup from json file so we don't ever do this again
            del libraries[library_id]
            if len(libraries) == 0:
                # We have migrated the last library for this user
                del plugin_prefs["libraries"]
            else:
                plugin_prefs["libraries"] = libraries

    if library_config is None:
        library_config = db.prefs.get_namespaced(
            PREFS_NAMESPACE, PREFS_KEY_SETTINGS, copy.deepcopy(DEFAULT_LIBRARY_VALUES)
        )

    migrate_library_config_if_required(db, library_config)
    return library_config


def set_library_config(db, library_config):
    db.prefs.set_namespaced(PREFS_NAMESPACE, PREFS_KEY_SETTINGS, library_config)


class ConfigWidget(QWidget):

    def __init__(self, plugin_action):
        QWidget.__init__(self)
        self.plugin_action = plugin_action
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        self.setup_tab = SetupTab(self)
        layout.addWidget(self.setup_tab)

    def save_settings(self):
        new_prefs = {}
        new_prefs[KEY_OVERWRITE_EXISTING] = self.setup_tab.overwrite_checkbox.isChecked()
        new_prefs[KEY_ASK_FOR_CONFIRMATION] = self.setup_tab.ask_for_confirmation_checkbox.isChecked()
        new_prefs[KEY_PREFER_HTML] = self.setup_tab.prefer_html_checkbox.isChecked()

        plugin_prefs[STORE_NAME] = new_prefs

        db = self.plugin_action.gui.current_db
        library_config = get_library_config(db)
        max_tags: int = 50
        max_tags_str = unicode(self.setup_tab.max_tags_ledit.text()).strip()
        try:
            max_tags = int(max_tags_str)
        except ValueError as exc:
            raise ValueError(_(f"Invalid maximum number of tags specified: {max_tags_str}")) from exc  # type: ignore # pylint: disable=undefined-variable
        library_config[KEY_MAX_TAGS] = max_tags

        library_config[KEY_STEAM_CUSTOM_COLUMN] = self.setup_tab.steam_column_combo.get_selected_column()
        library_config[KEY_TAGS_CUSTOM_COLUMN] = self.setup_tab.tags_column_combo.get_selected_column()
        library_config[KEY_STAR_RATING_CUSTOM_COLUMN] = self.setup_tab.star_rating_column_combo.get_selected_column()
        library_config[KEY_RATING_COUNT_CUSTOM_COLUMN] = self.setup_tab.rating_count_column_combo.get_selected_column()
        set_library_config(db, library_config)

    def get_custom_int_columns(self):
        column_types = ["float", "int"]
        custom_columns = self.plugin_action.gui.library_view.model().custom_columns
        available_columns = {}
        for key, column in custom_columns.items():
            typ = column["datatype"]
            if typ in column_types:
                available_columns[key] = column
        return available_columns

    def get_custom_float_columns(self):
        column_types = ["float"]
        custom_columns = self.plugin_action.gui.library_view.model().custom_columns
        available_columns = {}
        for key, column in custom_columns.items():
            typ = column["datatype"]
            if typ in column_types:
                available_columns[key] = column
        return available_columns

    def get_custom_tag_columns(self):
        column_types = ["text"]
        custom_columns = self.plugin_action.gui.library_view.model().custom_columns
        available_columns = {}
        for key, column in custom_columns.items():
            typ = column["datatype"]
            if typ in column_types:
                available_columns[key] = column
        return available_columns

    def _link_activated(self, url):
        open_url(QUrl(url))

    def edit_shortcuts(self):
        d = KeyboardConfigDialog(self.plugin_action.gui, self.plugin_action.action_spec[0])
        if d.exec_() == d.Accepted:
            self.plugin_action.gui.keyboard.finalize()

    def view_prefs(self):
        d = PrefsViewerDialog(self.plugin_action.gui, PREFS_NAMESPACE)
        d.exec_()


class SetupTab(QWidget):

    def __init__(self, parent_dialog):
        self.parent_dialog = parent_dialog
        QWidget.__init__(self)
        layout = QVBoxLayout()
        self.setLayout(layout)

        c = plugin_prefs[STORE_NAME]
        overwrite_existing = c.get(KEY_OVERWRITE_EXISTING, DEFAULT_STORE_VALUES[KEY_OVERWRITE_EXISTING])
        ask_for_confirmation = c.get(KEY_ASK_FOR_CONFIRMATION, DEFAULT_STORE_VALUES[KEY_ASK_FOR_CONFIRMATION])
        prefer_html = c.get(KEY_PREFER_HTML, DEFAULT_STORE_VALUES[KEY_PREFER_HTML])
        library_config = get_library_config(self.parent_dialog.plugin_action.gui.current_db)
        max_tags = library_config.get(KEY_MAX_TAGS, DEFAULT_LIBRARY_VALUES[KEY_MAX_TAGS])

        # --- General options ---
        layout.addSpacing(5)
        general_group_box = QGroupBox(_("General options:"), self)  # type: ignore # pylint: disable=undefined-variable
        layout.addWidget(general_group_box)
        general_group_box_layout = QGridLayout()
        general_group_box.setLayout(general_group_box_layout)

        self.overwrite_checkbox = QCheckBox(
            _("&Refresh existing fields when downloading from Romance.io"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        self.overwrite_checkbox.setToolTip(
            _(  # type: ignore # pylint: disable=undefined-variable
                "When checked (default), downloading fields will update all configured\n"
                "fields with the latest data from Romance.io, even if they already have values.\n"
                "The Romance.io ID is never overwritten to avoid unnecessary searches.\n"
                "To change or re-download the ID, manually delete it from the book's identifiers.\n\n"
                "Uncheck this option if you have manually edited field values and don't\n"
                "want them overwritten. The plugin will then only populate empty fields."
            )
        )
        self.overwrite_checkbox.setChecked(overwrite_existing)
        general_group_box_layout.addWidget(self.overwrite_checkbox, 1, 0, 1, -1)

        self.ask_for_confirmation_checkbox = QCheckBox(_("&Prompt to save fields after downloading"), self)  # type: ignore # pylint: disable=undefined-variable
        self.ask_for_confirmation_checkbox.setToolTip(
            _(  # type: ignore # pylint: disable=undefined-variable
                "Uncheck this option if you want changes applied without\n"
                "a confirmation dialog. There is a small risk with this\n"
                "option unchecked that if you are making other changes to\n"
                "this book record at the same time they will be lost."
            )
        )
        self.ask_for_confirmation_checkbox.setChecked(ask_for_confirmation)
        general_group_box_layout.addWidget(self.ask_for_confirmation_checkbox, 2, 0, 1, -1)

        self.prefer_html_checkbox = QCheckBox(
            _("&Get tags directly from website HTML (slower)"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        self.prefer_html_checkbox.setToolTip(
            _(  # type: ignore # pylint: disable=undefined-variable
                "When checked, the plugin fetches tags directly from the Romance.io\n"
                "website instead of the JSON API. This ensures tags match exactly what\n"
                "you see on the website - some tags may be missing or slightly different\n"
                "when using the JSON API.\n\n"
                "Note: Website fetching requires opening a browser window and is\n"
                "slower than the JSON API. Leave unchecked for faster downloads."
            )
        )
        self.prefer_html_checkbox.setChecked(prefer_html)
        general_group_box_layout.addWidget(self.prefer_html_checkbox, 3, 0, 1, -1)

        # --- Steam rating ---
        layout.addSpacing(5)
        steam_group_box = QGroupBox(_("Steam rating options:"), self)  # type: ignore # pylint: disable=undefined-variable
        layout.addWidget(steam_group_box)
        steam_group_box_layout = QGridLayout()
        steam_group_box.setLayout(steam_group_box_layout)

        steam_column_label = QLabel(_("&Steam column:"), self)  # type: ignore # pylint: disable=undefined-variable
        tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose a custom column you have created with the type "Integer".\n'
            "Leave this blank if you do not want to download steam rating from Romance.io."
        )
        steam_column_label.setToolTip(tool_tip)
        steam_col = library_config.get(KEY_STEAM_CUSTOM_COLUMN, "")
        avail_int_columns = self.parent_dialog.get_custom_int_columns()
        self.steam_column_combo = CustomColumnComboBox(self, avail_int_columns, steam_col)
        self.steam_column_combo.setToolTip(tool_tip)
        steam_column_label.setBuddy(self.steam_column_combo)
        steam_group_box_layout.addWidget(steam_column_label, 0, 0, 1, 1)
        steam_group_box_layout.addWidget(self.steam_column_combo, 0, 1, 1, 3)

        # --- Romance.io Tags ---
        layout.addSpacing(5)
        tags_group_box = QGroupBox(_("Romance.io tag options:"), self)  # type: ignore # pylint: disable=undefined-variable
        layout.addWidget(tags_group_box)
        tags_group_box_layout = QGridLayout()
        tags_group_box.setLayout(tags_group_box_layout)

        tags_column_label = QLabel(_("&Tags column:"), self)  # type: ignore # pylint: disable=undefined-variable
        tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose a custom column you have created with the type "Comma separated text".\n'
            "Leave this blank if you do not want to download tags from Romance.io."
        )
        tags_column_label.setToolTip(tool_tip)
        tags_col = library_config.get(KEY_TAGS_CUSTOM_COLUMN, "")
        avail_tag_columns = self.parent_dialog.get_custom_tag_columns()
        self.tags_column_combo = CustomColumnComboBox(self, avail_tag_columns, tags_col)
        self.tags_column_combo.setToolTip(tool_tip)
        tags_column_label.setBuddy(self.tags_column_combo)
        tags_group_box_layout.addWidget(tags_column_label, 0, 0, 1, 1)
        tags_group_box_layout.addWidget(self.tags_column_combo, 0, 1, 1, 3)

        self.max_tags_label = QLabel(_("&Maximum tags to download:"), self)  # type: ignore # pylint: disable=undefined-variable
        tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            "Specify the maximum number of tags to\n"
            "download (e.g. the top 10 most upvoted).\n"
            "Leaving this blank will download all tags."
        )
        self.max_tags_label.setToolTip(tool_tip)
        self.max_tags_ledit = QLineEdit(str(max_tags), self)
        self.max_tags_ledit.setToolTip(tool_tip)
        self.max_tags_label.setBuddy(self.max_tags_ledit)
        tags_group_box_layout.addWidget(self.max_tags_label, 1, 0, 1, 1)
        tags_group_box_layout.addWidget(self.max_tags_ledit, 1, 1, 1, 3)

        # --- Star Rating ---
        layout.addSpacing(5)
        star_rating_group_box = QGroupBox(_("Star rating options:"), self)  # type: ignore # pylint: disable=undefined-variable
        layout.addWidget(star_rating_group_box)
        star_rating_group_box_layout = QGridLayout()
        star_rating_group_box.setLayout(star_rating_group_box_layout)

        star_rating_column_label = QLabel(_("Star rating &column:"), self)  # type: ignore # pylint: disable=undefined-variable
        tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose a custom column you have created with the type "Floating point numbers".\n'
            "Leave this blank if you do not want to download star rating from Romance.io."
        )
        star_rating_column_label.setToolTip(tool_tip)
        star_rating_col = library_config.get(KEY_STAR_RATING_CUSTOM_COLUMN, "")
        avail_float_columns = self.parent_dialog.get_custom_float_columns()
        self.star_rating_column_combo = CustomColumnComboBox(self, avail_float_columns, star_rating_col)
        self.star_rating_column_combo.setToolTip(tool_tip)
        star_rating_column_label.setBuddy(self.star_rating_column_combo)
        star_rating_group_box_layout.addWidget(star_rating_column_label, 0, 0, 1, 1)
        star_rating_group_box_layout.addWidget(self.star_rating_column_combo, 0, 1, 1, 3)

        # --- Rating Count ---
        layout.addSpacing(5)
        rating_count_group_box = QGroupBox(_("Rating count options:"), self)  # type: ignore # pylint: disable=undefined-variable
        layout.addWidget(rating_count_group_box)
        rating_count_group_box_layout = QGridLayout()
        rating_count_group_box.setLayout(rating_count_group_box_layout)

        rating_count_column_label = QLabel(_("Rating &number column:"), self)  # type: ignore # pylint: disable=undefined-variable
        tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose a custom column you have created with the type "Integer".\n'
            "Leave this blank if you do not want to download rating count from Romance.io."
        )
        rating_count_column_label.setToolTip(tool_tip)
        rating_count_col = library_config.get(KEY_RATING_COUNT_CUSTOM_COLUMN, "")
        self.rating_count_column_combo = CustomColumnComboBox(self, avail_int_columns, rating_count_col)
        self.rating_count_column_combo.setToolTip(tool_tip)
        rating_count_column_label.setBuddy(self.rating_count_column_combo)
        rating_count_group_box_layout.addWidget(rating_count_column_label, 0, 0, 1, 1)
        rating_count_group_box_layout.addWidget(self.rating_count_column_combo, 0, 1, 1, 3)

        # --- Buttons ---
        layout.addSpacing(10)
        button_layout = QHBoxLayout()
        keyboard_shortcuts_button = QPushButton(" " + _("&Keyboard shortcuts"), self)  # type: ignore # pylint: disable=undefined-variable
        keyboard_shortcuts_button.setToolTip(_("Edit the keyboard shortcuts associated with this plugin"))  # type: ignore # pylint: disable=undefined-variable
        keyboard_shortcuts_button.clicked.connect(self.parent_dialog.edit_shortcuts)
        view_prefs_button = QPushButton(" " + _("&Library preferences"), self)  # type: ignore # pylint: disable=undefined-variable
        view_prefs_button.setToolTip(_("View data stored in the library database for this plugin"))  # type: ignore # pylint: disable=undefined-variable
        view_prefs_button.clicked.connect(self.parent_dialog.view_prefs)
        button_layout.addWidget(keyboard_shortcuts_button, 1)
        button_layout.addWidget(view_prefs_button, 1)
        layout.addLayout(button_layout)

        layout.addStretch(1)
