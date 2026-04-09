import copy

from six import text_type as unicode

# pylint: disable=duplicate-code  # Standard Calibre plugin import pattern
# Maintain backwards compatibility with older versions of Qt and calibre.
try:
    from qt.core import (
        QTableWidgetItem,
        QVBoxLayout,
        Qt,
        QGroupBox,
        QTableWidget,
        QCheckBox,
        QAbstractItemView,
        QHBoxLayout,
        QIcon,
        QInputDialog,
        QToolButton,
        QSpacerItem,
    )
except ImportError:
    from PyQt5.Qt import (
        QTableWidgetItem,
        QVBoxLayout,
        Qt,
        QGroupBox,
        QTableWidget,
        QCheckBox,
        QAbstractItemView,
        QHBoxLayout,
        QIcon,
        QInputDialog,
        QToolButton,
        QSpacerItem,
    )

# Pull in translation files for _() strings
try:
    load_translations()  # type: ignore[name-defined]  # pylint: disable=undefined-variable
except NameError:
    pass  # load_translations() added in calibre 1.9

from calibre.gui2 import get_current_db, question_dialog, error_dialog
from calibre.gui2.complete2 import EditWithComplete
from calibre.gui2.metadata.config import ConfigWidget as DefaultConfigWidget
from calibre.utils.config import JSONConfig

from calibre_plugins.romanceio.common_compatibility import (  # type: ignore[import-not-found]  # pylint: disable=import-error
    qSizePolicy_Expanding,
    qSizePolicy_Minimum,
)
from calibre_plugins.romanceio.common_icons import get_icon  # type: ignore[import-not-found]  # pylint: disable=import-error
from calibre_plugins.romanceio.common_widgets import ReadOnlyTableWidgetItem  # type: ignore[import-not-found]  # pylint: disable=import-error

# pylint: enable=duplicate-code


from calibre_plugins.romanceio.config_defaults import (  # type: ignore[import-not-found]  # pylint: disable=import-error
    STORE_NAME,
    KEY_GENRE_MAPPINGS,
    KEY_MAP_GENRES,
    DEFAULT_GENRE_MAPPINGS,
)

DEFAULT_STORE_VALUES = {
    KEY_MAP_GENRES: True,
    KEY_GENRE_MAPPINGS: copy.deepcopy(DEFAULT_GENRE_MAPPINGS),
}

# This is where all preferences for this plugin will be stored
plugin_prefs = JSONConfig("plugins/RomanceIO")

plugin_prefs.defaults[STORE_NAME] = DEFAULT_STORE_VALUES


def get_plugin_pref(store_name, option):
    c = plugin_prefs[store_name]
    default_value = plugin_prefs.defaults[store_name][option]
    return c.get(option, default_value)


def get_plugin_prefs(store_name, fill_defaults=False):
    if fill_defaults:
        c = get_prefs(plugin_prefs, store_name)
    else:
        c = plugin_prefs[store_name]
    return c


def get_prefs(prefs_store, store_name):
    store = {}
    if prefs_store and prefs_store[store_name]:
        for key in plugin_prefs.defaults[store_name]:
            store[key] = prefs_store[store_name].get(key, plugin_prefs.defaults[store_name][key])
    else:
        store = plugin_prefs.defaults[store_name]
    return store


class GenreTagMappingsTableWidget(QTableWidget):
    def __init__(self, parent, all_tags):
        QTableWidget.__init__(self, parent)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tags_values = all_tags

    def populate_table(self, tag_mappings):
        self.clear()
        self.setAlternatingRowColors(True)
        self.setRowCount(len(tag_mappings))
        header_labels = [_("Romance.io Genre"), _("Maps to Calibre Tag")]  # type: ignore # pylint: disable=undefined-variable
        self.setColumnCount(len(header_labels))
        self.setHorizontalHeaderLabels(header_labels)
        self.verticalHeader().setDefaultSectionSize(24)
        self.horizontalHeader().setStretchLastSection(True)

        for row, genre in enumerate(sorted(tag_mappings.keys(), key=lambda s: (s.lower(), s))):
            self.populate_table_row(row, genre, sorted(tag_mappings[genre]))

        self.resizeColumnToContents(0)
        self.set_minimum_column_width(0, 200)
        self.setSortingEnabled(False)
        if len(tag_mappings) > 0:
            self.selectRow(0)

    def set_minimum_column_width(self, col, minimum):
        if self.columnWidth(col) < minimum:
            self.setColumnWidth(col, minimum)

    def populate_table_row(self, row, genre, tags):
        self.setItem(row, 0, ReadOnlyTableWidgetItem(genre))
        tags_value = ", ".join(tags)
        # Add a widget under the cell just for sorting purposes
        self.setItem(row, 1, QTableWidgetItem(tags_value))
        self.setCellWidget(row, 1, self.create_tags_edit(tags_value))

    def create_tags_edit(self, value):
        tags_edit = EditWithComplete(self)
        tags_edit.set_add_separator(False)
        tags_edit.update_items_cache(self.tags_values)
        tags_edit.setText(value)
        return tags_edit

    def tags_editing_finished(self, row, tags_edit):
        # Update our underlying widget for sorting
        self.item(row, 1).setText(tags_edit.text())

    def get_data(self):
        tag_mappings = {}
        for row in range(self.rowCount()):
            genre = unicode(self.item(row, 0).text()).strip()
            tags_text = unicode(self.cellWidget(row, 1).text()).strip()
            tag_values = tags_text.split(",")
            tags_list = []
            for tag in tag_values:
                if len(tag.strip()) > 0:
                    tags_list.append(tag.strip())
            tag_mappings[genre] = tags_list
        return tag_mappings

    def select_genre(self, genre_name):
        for row in range(self.rowCount()):
            if unicode(self.item(row, 0).text()) == genre_name:
                self.setCurrentCell(row, 1)
                return

    def get_selected_genre(self):
        if self.currentRow() >= 0:
            return unicode(self.item(self.currentRow(), 0).text())
        return None


class ConfigWidget(DefaultConfigWidget):

    def __init__(self, plugin):
        DefaultConfigWidget.__init__(self, plugin)
        c = get_plugin_prefs(STORE_NAME, fill_defaults=True)
        all_tags = get_current_db().all_tags()  # type: ignore[attr-defined]

        self.gb.setMaximumHeight(80)
        genre_group_box = QGroupBox(_("Romance.io tag to Calibre tag mappings"), self)  # type: ignore # pylint: disable=undefined-variable
        self.l.addWidget(genre_group_box, self.l.rowCount(), 0, 1, 2)
        genre_group_box_layout = QVBoxLayout()
        genre_group_box.setLayout(genre_group_box_layout)

        self.map_genres_checkbox = QCheckBox(
            _("Filter and map Romance.io tags to calibre tags"), self  # type: ignore # pylint: disable=undefined-variable
        )
        self.map_genres_checkbox.setToolTip(
            _(  # type: ignore # pylint: disable=undefined-variable
                "When checked, only specific calibre tags will be used as per below.\n"
                "When unchecked, all Romance.io tags will be added as Calibre tags."
            )
        )
        self.map_genres_checkbox.setChecked(c.get(KEY_MAP_GENRES, DEFAULT_STORE_VALUES[KEY_MAP_GENRES]))
        genre_group_box_layout.addWidget(self.map_genres_checkbox)

        tags_layout = QHBoxLayout()
        genre_group_box_layout.addLayout(tags_layout)

        self.edit_table = GenreTagMappingsTableWidget(self, all_tags)
        tags_layout.addWidget(self.edit_table)
        button_layout = QVBoxLayout()
        tags_layout.addLayout(button_layout)
        add_mapping_button = QToolButton(self)
        add_mapping_button.setToolTip(_("Add genre mapping"))  # type: ignore # pylint: disable=undefined-variable
        add_mapping_button.setIcon(QIcon(I("plus.png")))  # type: ignore # pylint: disable=undefined-variable
        add_mapping_button.clicked.connect(self.add_mapping)
        button_layout.addWidget(add_mapping_button)
        spacer_item_1 = QSpacerItem(20, 40, qSizePolicy_Minimum, qSizePolicy_Expanding)
        button_layout.addItem(spacer_item_1)
        remove_mapping_button = QToolButton(self)
        remove_mapping_button.setToolTip(_("Delete genre mapping"))  # type: ignore # pylint: disable=undefined-variable
        remove_mapping_button.setIcon(QIcon(I("minus.png")))  # type: ignore # pylint: disable=undefined-variable
        remove_mapping_button.clicked.connect(self.delete_mapping)
        button_layout.addWidget(remove_mapping_button)
        spacer_item_3 = QSpacerItem(20, 40, qSizePolicy_Minimum, qSizePolicy_Expanding)
        button_layout.addItem(spacer_item_3)
        rename_genre_button = QToolButton(self)
        rename_genre_button.setToolTip(_("Rename Romance.io genre"))  # type: ignore # pylint: disable=undefined-variable
        rename_genre_button.setIcon(QIcon(I("edit-undo.png")))  # type: ignore # pylint: disable=undefined-variable
        rename_genre_button.clicked.connect(self.rename_genre)
        button_layout.addWidget(rename_genre_button)
        spacer_item_2 = QSpacerItem(20, 40, qSizePolicy_Minimum, qSizePolicy_Expanding)
        button_layout.addItem(spacer_item_2)
        reset_defaults_button = QToolButton(self)
        reset_defaults_button.setToolTip(_("Reset to plugin default mappings"))  # type: ignore # pylint: disable=undefined-variable
        reset_defaults_button.setIcon(get_icon("clear_left"))
        reset_defaults_button.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_defaults_button)
        self.l.setRowStretch(self.l.rowCount() - 1, 2)

        self.edit_table.populate_table(c[KEY_GENRE_MAPPINGS])
        self._restore_defaults_button = None

    def commit(self):
        DefaultConfigWidget.commit(self)
        new_prefs = {}
        new_prefs[KEY_MAP_GENRES] = self.map_genres_checkbox.checkState() == Qt.Checked
        new_prefs[KEY_GENRE_MAPPINGS] = self.edit_table.get_data()
        plugin_prefs[STORE_NAME] = new_prefs

    def add_mapping(self):
        new_genre_name, ok = QInputDialog.getText(
            self,
            _("Add new mapping"),  # type: ignore # pylint: disable=undefined-variable
            _("Enter a Romance.io tag name to create a mapping for:"),  # type: ignore # pylint: disable=undefined-variable
            text="",
        )
        if not ok:
            # Operation cancelled
            return
        new_genre_name = unicode(new_genre_name).strip()
        if not new_genre_name:
            return
        # Verify it does not clash with any other mappings in the list
        data = self.edit_table.get_data()
        for genre_name in data:
            if genre_name.lower() == new_genre_name.lower():
                error_dialog(
                    self,
                    _("Add Failed"),  # type: ignore # pylint: disable=undefined-variable
                    _("A genre with the same name already exists"),  # type: ignore # pylint: disable=undefined-variable
                    show=True,
                )
                return
        data[new_genre_name] = []
        self.edit_table.populate_table(data)
        self.edit_table.select_genre(new_genre_name)

    def delete_mapping(self):
        if not self.edit_table.selectionModel().hasSelection():
            return
        if not question_dialog(
            self,
            _("Are you sure?"),  # type: ignore # pylint: disable=undefined-variable
            "<p>" + _("Are you sure you want to delete the selected genre mappings?"),  # type: ignore # pylint: disable=undefined-variable
            show_copy_button=False,
        ):
            return
        for row in reversed(sorted(self.edit_table.selectionModel().selectedRows())):
            self.edit_table.removeRow(row.row())

    def rename_genre(self):
        selected_genre = self.edit_table.get_selected_genre()
        if not selected_genre:
            return
        new_genre_name, ok = QInputDialog.getText(
            self,
            _("Add new mapping"),  # type: ignore # pylint: disable=undefined-variable
            _("Enter a Romance.io tag name to create a mapping for:"),  # type: ignore # pylint: disable=undefined-variable
            text=selected_genre,
        )
        if not ok:
            # Operation cancelled
            return
        new_genre_name = unicode(new_genre_name).strip()
        if not new_genre_name or new_genre_name == selected_genre:
            return
        data = self.edit_table.get_data()
        if new_genre_name.lower() != selected_genre.lower():
            # Verify it does not clash with any other mappings in the list
            for genre_name in data:
                if genre_name.lower() == new_genre_name.lower():
                    error_dialog(
                        self,
                        _("Rename Failed"),  # type: ignore # pylint: disable=undefined-variable
                        _("A genre with the same name already exists"),  # type: ignore # pylint: disable=undefined-variable
                        show=True,
                    )
                    return
        data[new_genre_name] = data[selected_genre]
        del data[selected_genre]
        self.edit_table.populate_table(data)
        self.edit_table.select_genre(new_genre_name)

    def restore_defaults(self):
        """Reset all plugin settings to their default values (no confirmation prompt)."""
        self.fields_model.restore_defaults()
        self.map_genres_checkbox.setChecked(DEFAULT_STORE_VALUES[KEY_MAP_GENRES])
        self.edit_table.populate_table(copy.deepcopy(DEFAULT_GENRE_MAPPINGS))

    def reset_to_defaults(self):
        if not question_dialog(
            self,
            _("Are you sure?"),  # type: ignore # pylint: disable=undefined-variable
            "<p>"
            + _("Are you sure you want to reset to the plugin default genre mappings?"),  # type: ignore # pylint: disable=undefined-variable
            show_copy_button=False,
        ):
            return
        self.restore_defaults()

    def showEvent(self, event):  # pylint: disable=invalid-name
        super().showEvent(event)
        self._connect_restore_defaults()

    def hideEvent(self, event):  # pylint: disable=invalid-name
        self._disconnect_restore_defaults()
        super().hideEvent(event)

    def _connect_restore_defaults(self):
        """Connect our restore_defaults to the outer preferences dialog 'Restore Defaults' button."""
        if self._restore_defaults_button is not None:
            return
        try:
            from qt.core import QDialog, QDialogButtonBox as QBB  # pylint: disable=import-outside-toplevel
        except ImportError:
            from PyQt5.Qt import QDialog, QDialogButtonBox as QBB  # pylint: disable=import-outside-toplevel
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, QDialog):
                for bb in parent.findChildren(QBB):
                    btn = bb.button(QBB.StandardButton.RestoreDefaults)
                    if btn is not None:
                        btn.clicked.connect(self.restore_defaults)
                        self._restore_defaults_button = btn
                        return
                break
            parent = parent.parent()

    def _disconnect_restore_defaults(self):
        """Disconnect our restore_defaults from the outer preferences dialog 'Restore Defaults' button."""
        if self._restore_defaults_button is not None:
            try:
                self._restore_defaults_button.clicked.disconnect(self.restore_defaults)
            except (RuntimeError, TypeError):
                pass
            self._restore_defaults_button = None
