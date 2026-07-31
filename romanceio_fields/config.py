"""
Allow the user to configure the plugin.
"""

import copy
from typing import Any, Dict, List, TYPE_CHECKING

from six import text_type as unicode  # type: ignore[import-untyped]

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
        QScrollArea,
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
        QScrollArea,
    )

from calibre.gui2 import error_dialog, open_url
from calibre.utils.config import JSONConfig

from .common_dialogs import KeyboardConfigDialog, PrefsViewerDialog  # pylint: disable=import-error
from .common_compatibility import PREFER_HTML_TOOLTIP  # pylint: disable=import-error
from .common_widgets import CustomColumnComboBox  # pylint: disable=import-error

if TYPE_CHECKING:

    def _(text: str) -> str:
        """Type-checking declaration for Calibre's runtime translation function."""
        ...


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
KEY_GENERAL_TAGS_CUSTOM_COLUMN = "customColumnGeneralTags"
KEY_CONTENT_WARNINGS_CUSTOM_COLUMN = "customColumnContentWarnings"
KEY_GEOGRAPHY_CUSTOM_COLUMN = "customColumnGeography"
KEY_FORMAT_TAGS_CUSTOM_COLUMN = "customColumnFormatTags"
KEY_STAR_RATING_CUSTOM_COLUMN = "customColumnStarRating"
KEY_RATING_COUNT_CUSTOM_COLUMN = "customColumnRatingCount"

STORE_NAME = "Options"
KEY_MAX_TAGS = "maxRomanceTags"
KEY_OVERWRITE_EXISTING = "overwriteExisting"
KEY_ASK_FOR_CONFIRMATION = "askForConfirmation"
KEY_PREFER_HTML = "preferHtmlParsing"

FIELD_STEAM_RATING = "SteamRating"
FIELD_ROMANCE_TAGS = "RomanceTags"
FIELD_GENERAL_TAGS = "GeneralTags"
FIELD_CONTENT_WARNINGS = "ContentWarnings"
FIELD_GEOGRAPHY = "GeographyTags"
FIELD_FORMAT_TAGS = "FormatTags"
FIELD_STAR_RATING = "StarRating"
FIELD_RATING_COUNT = "RatingCount"
ALL_FIELDS: Dict[str, str] = {
    FIELD_STEAM_RATING: KEY_STEAM_CUSTOM_COLUMN,
    FIELD_ROMANCE_TAGS: KEY_TAGS_CUSTOM_COLUMN,
    FIELD_GENERAL_TAGS: KEY_GENERAL_TAGS_CUSTOM_COLUMN,
    FIELD_CONTENT_WARNINGS: KEY_CONTENT_WARNINGS_CUSTOM_COLUMN,
    FIELD_GEOGRAPHY: KEY_GEOGRAPHY_CUSTOM_COLUMN,
    FIELD_FORMAT_TAGS: KEY_FORMAT_TAGS_CUSTOM_COLUMN,
    FIELD_STAR_RATING: KEY_STAR_RATING_CUSTOM_COLUMN,
    FIELD_RATING_COUNT: KEY_RATING_COUNT_CUSTOM_COLUMN,
}
CATEGORY_FIELD_TO_PARSED_KEY = {
    FIELD_GENERAL_TAGS: "general_tags",
    FIELD_CONTENT_WARNINGS: "content_warnings",
    FIELD_GEOGRAPHY: "geography_tags",
    FIELD_FORMAT_TAGS: "format_tags",
}
CATEGORY_FIELDS = frozenset(CATEGORY_FIELD_TO_PARSED_KEY)

DEFAULT_STORE_VALUES = {
    KEY_ASK_FOR_CONFIRMATION: False,
    KEY_OVERWRITE_EXISTING: True,
    KEY_PREFER_HTML: False,
}
DEFAULT_LIBRARY_VALUES: Dict[str, Any] = {
    KEY_MAX_TAGS: 50,
    KEY_STEAM_CUSTOM_COLUMN: "",
    KEY_TAGS_CUSTOM_COLUMN: "",
    KEY_GENERAL_TAGS_CUSTOM_COLUMN: "",
    KEY_CONTENT_WARNINGS_CUSTOM_COLUMN: "",
    KEY_GEOGRAPHY_CUSTOM_COLUMN: "",
    KEY_FORMAT_TAGS_CUSTOM_COLUMN: "",
    KEY_STAR_RATING_CUSTOM_COLUMN: "",
    KEY_RATING_COUNT_CUSTOM_COLUMN: "",
}

PLUGIN_ICONS: List[str] = [
    "images/logo.png",
    "images/download.png",
]

KEY_SCHEMA_VERSION = "SchemaVersion"
DEFAULT_SCHEMA_VERSION = 1.63


# This is where all preferences for this plugin will be stored
plugin_prefs = JSONConfig("plugins/RomanceIOFields")

plugin_prefs.defaults[STORE_NAME] = DEFAULT_STORE_VALUES


def find_duplicate_column_mappings(field_to_column: Dict[str, str]) -> Dict[str, List[str]]:
    """Return destination columns selected by more than one plugin field."""
    fields_by_column: Dict[str, List[str]] = {}
    for field, column in field_to_column.items():
        if column:
            fields_by_column.setdefault(column, []).append(field)
    return {column: fields for column, fields in fields_by_column.items() if len(fields) > 1}


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

    if schema_version < 1.63:
        library_config.setdefault(KEY_GENERAL_TAGS_CUSTOM_COLUMN, "")
        library_config.setdefault(KEY_CONTENT_WARNINGS_CUSTOM_COLUMN, "")
        library_config.setdefault(KEY_GEOGRAPHY_CUSTOM_COLUMN, "")
        library_config.setdefault(KEY_FORMAT_TAGS_CUSTOM_COLUMN, "")

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
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.setup_tab)
        layout.addWidget(scroll_area)

    def _selected_columns(self) -> Dict[str, str]:
        """Return the current field-to-column selections from the form."""
        def selected_column(combo: Any) -> str:
            value = combo.get_selected_column()
            return value if isinstance(value, str) else ""

        return {
            FIELD_STEAM_RATING: selected_column(self.setup_tab.steam_column_combo),
            FIELD_ROMANCE_TAGS: selected_column(self.setup_tab.tags_column_combo),
            FIELD_GENERAL_TAGS: selected_column(self.setup_tab.general_tags_column_combo),
            FIELD_CONTENT_WARNINGS: selected_column(self.setup_tab.content_warnings_column_combo),
            FIELD_GEOGRAPHY: selected_column(self.setup_tab.geography_column_combo),
            FIELD_FORMAT_TAGS: selected_column(self.setup_tab.format_tags_column_combo),
            FIELD_STAR_RATING: selected_column(self.setup_tab.star_rating_column_combo),
            FIELD_RATING_COUNT: selected_column(self.setup_tab.rating_count_column_combo),
        }

    def validate(self):
        """Prevent two downloaded values from silently overwriting one column."""
        duplicate_columns = find_duplicate_column_mappings(self._selected_columns())
        if not duplicate_columns:
            return True

        field_labels = {
            FIELD_STEAM_RATING: _("Steam rating"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
            FIELD_ROMANCE_TAGS: _("All tags (combined)"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
            FIELD_GENERAL_TAGS: _("General tags"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
            FIELD_CONTENT_WARNINGS: _("Content warnings"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
            FIELD_GEOGRAPHY: _("Geography"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
            FIELD_FORMAT_TAGS: _("Format tags"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
            FIELD_STAR_RATING: _("Star rating"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
            FIELD_RATING_COUNT: _("Rating count"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
        }
        details = "\n".join(
            f"{column}: {', '.join(field_labels[field] for field in fields)}"
            for column, fields in sorted(duplicate_columns.items())
        )
        error_dialog(
            self,
            _("Duplicate custom columns"),  # type: ignore[name-defined]  # pylint: disable=undefined-variable
            _(  # type: ignore[name-defined]  # pylint: disable=undefined-variable
                "Each Romance.io field must use a different custom column. "
                "Choose a different column for the following selections:\n\n"
            )
            + details,
            show=True,
        )
        return False

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

        selected_columns = self._selected_columns()
        for field, preference_key in ALL_FIELDS.items():
            library_config[preference_key] = selected_columns[field]
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
            _("&Get tags directly from website (slower but includes additional community tags)"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        self.prefer_html_checkbox.setToolTip(
            _(PREFER_HTML_TOOLTIP)  # type: ignore # pylint: disable=undefined-variable
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
            'Choose a custom column you have created with the type "Integers".\n'
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

        tags_column_label = QLabel(
            _("All &tags column (combined):"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose a custom column you have created with the type "Comma separated text".\n'
            "Stores every Romance.io tag group together without category prefixes, including\n"
            "general tags, content warnings, geography, and format. For example, a book might\n"
            "include 'slow burn', 'past child abuse', 'michigan', and 'first person pov'.\n"
            "This preserves the existing behavior; category columns below are additional copies.\n"
            "Leave this blank if you do not want the combined tag list."
        )
        tags_column_label.setToolTip(tool_tip)
        tags_col = library_config.get(KEY_TAGS_CUSTOM_COLUMN, "")
        avail_tag_columns = self.parent_dialog.get_custom_tag_columns()
        self.tags_column_combo = CustomColumnComboBox(self, avail_tag_columns, tags_col)
        self.tags_column_combo.setToolTip(tool_tip)
        tags_column_label.setBuddy(self.tags_column_combo)
        tags_group_box_layout.addWidget(tags_column_label, 0, 0, 1, 1)
        tags_group_box_layout.addWidget(self.tags_column_combo, 0, 1, 1, 3)

        self.max_tags_label = QLabel(
            _("Ma&ximum combined tags:"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            "Specify the maximum number of tags written to the combined tags column\n"
            "(e.g. keep the first 10 tags returned by Romance.io).\n"
            "Optional category columns always receive their complete matching groups."
        )
        self.max_tags_label.setToolTip(tool_tip)
        self.max_tags_ledit = QLineEdit(str(max_tags), self)
        self.max_tags_ledit.setToolTip(tool_tip)
        self.max_tags_label.setBuddy(self.max_tags_ledit)
        max_tags_layout = QHBoxLayout()
        max_tags_layout.setContentsMargins(20, 0, 0, 0)
        max_tags_layout.addWidget(self.max_tags_label)
        max_tags_layout.addWidget(self.max_tags_ledit)
        max_tags_layout.addStretch(1)
        tags_group_box_layout.addLayout(max_tags_layout, 1, 0, 1, 4)

        general_tags_column_label = QLabel(
            _("General tags c&olumn:"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        general_tags_tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose an optional custom column with the type "Comma separated text".\n'
            "General tags are Romance.io's ordinary book descriptors, such as\n"
            "'enemies to lovers', 'slow burn', or 'small town'. They exclude content\n"
            "warnings, geography, and format tags. This is an additional copy and\n"
            "does not change the combined tags column."
        )
        general_tags_column_label.setToolTip(general_tags_tool_tip)
        general_tags_col = library_config.get(KEY_GENERAL_TAGS_CUSTOM_COLUMN, "")
        self.general_tags_column_combo = CustomColumnComboBox(self, avail_tag_columns, general_tags_col)
        self.general_tags_column_combo.setToolTip(general_tags_tool_tip)
        general_tags_column_label.setBuddy(self.general_tags_column_combo)
        tags_group_box_layout.addWidget(general_tags_column_label, 2, 0, 1, 1)
        tags_group_box_layout.addWidget(self.general_tags_column_combo, 2, 1, 1, 3)

        content_warnings_column_label = QLabel(
            _("Content &warnings column:"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        content_warnings_tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose an optional custom column with the type "Comma separated text".\n'
            "Content warnings describe potentially sensitive material, such as 'past child\n"
            "abuse', 'mental trauma', or 'gambling'. This is an additional copy and does not\n"
            "change the combined tags column."
        )
        content_warnings_column_label.setToolTip(content_warnings_tool_tip)
        content_warnings_col = library_config.get(KEY_CONTENT_WARNINGS_CUSTOM_COLUMN, "")
        self.content_warnings_column_combo = CustomColumnComboBox(self, avail_tag_columns, content_warnings_col)
        self.content_warnings_column_combo.setToolTip(content_warnings_tool_tip)
        content_warnings_column_label.setBuddy(self.content_warnings_column_combo)
        tags_group_box_layout.addWidget(content_warnings_column_label, 3, 0, 1, 1)
        tags_group_box_layout.addWidget(self.content_warnings_column_combo, 3, 1, 1, 3)

        geography_column_label = QLabel(
            _("Geograph&y column:"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        geography_tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose an optional custom column with the type "Comma separated text".\n'
            "Geography tags describe where a story takes place, such as 'michigan', 'usa',\n"
            "or 'england'. This is an additional copy and does not change the combined tags column."
        )
        geography_column_label.setToolTip(geography_tool_tip)
        geography_col = library_config.get(KEY_GEOGRAPHY_CUSTOM_COLUMN, "")
        self.geography_column_combo = CustomColumnComboBox(self, avail_tag_columns, geography_col)
        self.geography_column_combo.setToolTip(geography_tool_tip)
        geography_column_label.setBuddy(self.geography_column_combo)
        tags_group_box_layout.addWidget(geography_column_label, 4, 0, 1, 1)
        tags_group_box_layout.addWidget(self.geography_column_combo, 4, 1, 1, 3)

        format_tags_column_label = QLabel(
            _("&Format tags column:"),  # type: ignore # pylint: disable=undefined-variable
            self,
        )
        format_tags_tool_tip = _(  # type: ignore # pylint: disable=undefined-variable
            'Choose an optional custom column with the type "Comma separated text".\n'
            "Format tags describe the book's presentation or structure, such as 'audiobook',\n"
            "'first person pov', 'Long: 400-599', or 'standalone or first in series'. Some\n"
            "length and series tags were historically omitted from the combined list, but are\n"
            "retained here. This additional column does not change the combined tags column."
        )
        format_tags_column_label.setToolTip(format_tags_tool_tip)
        format_tags_col = library_config.get(KEY_FORMAT_TAGS_CUSTOM_COLUMN, "")
        self.format_tags_column_combo = CustomColumnComboBox(self, avail_tag_columns, format_tags_col)
        self.format_tags_column_combo.setToolTip(format_tags_tool_tip)
        format_tags_column_label.setBuddy(self.format_tags_column_combo)
        tags_group_box_layout.addWidget(format_tags_column_label, 5, 0, 1, 1)
        tags_group_box_layout.addWidget(self.format_tags_column_combo, 5, 1, 1, 3)

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
            'Choose a custom column you have created with the type "Integers".\n'
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
