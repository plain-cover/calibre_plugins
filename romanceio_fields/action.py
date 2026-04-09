"""
A Calibre plugin that provides the action to download metadata from
Romance.io for selected book(s). An InterfaceAction plugin represents
an "action" that can be taken in Calibre's graphical user interface.
"""

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from functools import partial

# pylint: disable=duplicate-code  # Standard Calibre plugin import pattern
if TYPE_CHECKING:
    from qt.core import QToolButton, QMenu, QObject
else:
    try:
        from qt.core import QToolButton, QMenu, QObject
    except ImportError:
        from PyQt5.QtWidgets import QToolButton, QMenu
        from PyQt5.QtCore import QObject

# Pull in translation files for _() strings
try:
    load_translations()  # type: ignore[name-defined]  # pylint: disable=undefined-variable
except NameError:
    pass  # load_translations() added in calibre 1.9

from calibre.gui2 import question_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.dialogs.message_box import ErrorNotification
from calibre.utils.ipc.job import ParallelJob

from . import config as cfg
from .config import ALL_FIELDS
from .common_icons import set_plugin_icon_resources, get_icon  # pylint: disable=import-error
from .common_menus import unregister_menu_actions, create_menu_action_unique  # pylint: disable=import-error
from .common_dialogs import ProgressBarDialog  # pylint: disable=import-error
from .jobs import call_plugin_callback


class CustomActionParallelJob(ParallelJob):
    """
    Custom subclass to keep track of the additional args used when launching jobs.
    """

    # Attributes inherited from ParallelJob
    name: str
    description: str
    done: Optional[Dict[int, Dict[str, Any]]]

    # Additional attributes specific to this usage
    fields_to_cols_map: Dict[str, str]
    plugin_callback: Optional[Any]
    result: Optional[Dict[int, Dict[str, Any]]] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields_to_cols_map = {}
        self.plugin_callback = None
        self.result = None


class RomanceIOFieldsAction(InterfaceAction):

    name = "Romance.io Fields"
    # Create our top-level menu/toolbar action (text, icon_path, tooltip, keyboard shortcut)
    action_spec = (
        _("Romance.io"),  # type: ignore # pylint: disable=undefined-variable
        None,
        _(  # type: ignore # pylint: disable=undefined-variable
            "Download Romance.io metadata fields "  # fmt: skip
            "(steam rating, star rating, rating count, tags)"
        ),
        (),
    )
    popup_type = QToolButton.MenuButtonPopup
    action_type = "current"
    dont_add_to = frozenset(["context-menu-device"])

    # Type hints for attributes set in genesis()
    is_library_selected: bool
    menu: QMenu
    plugin_callback: Any
    pb: Any  # ProgressBarDialog - set in progressbar()

    def genesis(self):
        self.is_library_selected = True
        self.gui: QObject  # pylint: disable=attribute-defined-outside-init
        self.menu = QMenu(self.gui)
        # Read the plugin icons and store for potential sharing with the config widget
        icon_resources = self.load_resources(cfg.PLUGIN_ICONS)
        set_plugin_icon_resources(self.name, icon_resources)

        self.rebuild_menus()

        # Assign our menu to this action and an icon
        self.qaction.setMenu(self.menu)
        self.qaction.setIcon(get_icon(cfg.PLUGIN_ICONS[0]))
        self.qaction.triggered.connect(self.toolbar_triggered)
        self.menu.aboutToShow.connect(self.about_to_show_menu)

        # Used to store callback details when called from another plugin.
        self.plugin_callback = None

    def about_to_show_menu(self):
        self.rebuild_menus()

    def library_changed(self, db):  # pylint: disable=unused-argument
        # We need to reapply keyboard shortcuts after switching libraries
        self.rebuild_menus()

    def location_selected(self, loc):
        self.is_library_selected = loc == "library"

    def rebuild_menus(self):
        # Ensure any keyboard shortcuts from previous display of plugin menu are cleared
        unregister_menu_actions(self)

        m = self.menu
        m.clear()

        create_menu_action_unique(
            self,
            m,
            _("&Download fields for selected book(s)"),  # type: ignore # pylint: disable=undefined-variable
            "images/download.png",
            triggered=partial(self._get_fields_for_selected),
            unique_name="Download fields for selected book(s)",
            shortcut_name="Download fields for selected book(s)",
        )
        m.addSeparator()
        create_menu_action_unique(
            self,
            m,
            _("&Customize plugin") + "...",  # type: ignore # pylint: disable=undefined-variable
            "config.png",
            shortcut=(),
            triggered=self.show_configuration,
            unique_name="Customize plugin",
            shortcut_name="Customize plugin",
        )
        self.gui.keyboard.finalize()

    def toolbar_triggered(self):
        self._get_fields_for_selected()

    def _get_fields_for_selected(self) -> None:
        if not self.is_library_selected:
            return
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows or len(rows) == 0:
            return
        book_ids: List[int] = self.gui.library_view.get_selected_ids()

        fields_to_run = list(ALL_FIELDS.keys())
        any_valid, fields_to_cols_map = self._get_column_validity(fields_to_run)
        if not any_valid:
            if not question_dialog(
                self.gui,
                _("Configure plugin"),  # type: ignore # pylint: disable=undefined-variable
                "<p>"
                + _(  # type: ignore # pylint: disable=undefined-variable
                    "You must specify custom column(s) first. Do you want to configure this now?"
                ),
                show_copy_button=False,
            ):
                return
            self.show_configuration()
            return

        self._get_romanceio_fields(book_ids, fields_to_cols_map)

    def _get_column_validity(self, fields_to_run: List[str]) -> Tuple[bool, Dict[str, str]]:
        """
        Given a list of fields requested to retrieve, lookup what custom
        columns are configured and return a dict for each possible field
        and its associated custom column (blank if not to be run).
        """
        db = self.gui.current_db
        all_cols = db.field_metadata.custom_field_metadata()

        library_config = cfg.get_library_config(db)
        fields_to_cols_map: Dict[str, str] = {}
        any_valid = False
        for value, field_col_key in cfg.ALL_FIELDS.items():
            col = library_config.get(field_col_key, "")
            is_requested = value in fields_to_run
            is_valid = is_requested and len(col) > 0 and col in all_cols
            if not is_valid or not col:
                fields_to_cols_map[value] = ""
            else:
                any_valid = True
                fields_to_cols_map[value] = col
        return any_valid, fields_to_cols_map

    def metadata_download(
        self,
        book_ids: List[int],
        fields_to_run: List[str],
        plugin_callback: Optional[Dict[Any, Any]] = None,
    ) -> None:
        """
        This function is designed to be called from other plugins
        Note that the download functions can only be used if a
        custom column has been configured by the user first.

          book_ids - list of calibre book ids to run the metadata download against

          fields_to_run - list of field names to be run. Possible values:
              'SteamRating', 'RomanceTags'

          plugin_callback - This is a dictionary defining the callback function.
        """
        if fields_to_run is None or len(fields_to_run) == 0:
            print("Metadata download called but neither SteamRating nor RomanceTags requested")
            return

        # Verify we have a custom column configured to store the metadata
        any_valid, fields_to_cols_map = self._get_column_validity(fields_to_run)
        if not any_valid:
            if not question_dialog(
                self.gui,
                _("Configure plugin"),  # type: ignore # pylint: disable=undefined-variable
                "<p>"
                + _(  # type: ignore # pylint: disable=undefined-variable
                    "You must specify custom column(s) first. Do you want to configure this now?"
                ),
                show_copy_button=False,
            ):
                return
            self.show_configuration()
            return

        self.plugin_callback = plugin_callback

        self._get_romanceio_fields(book_ids, fields_to_cols_map)

    def _get_romanceio_fields(self, book_ids: List[int], fields_to_cols_map: Dict[str, str]) -> None:
        # Queue preparation job to run in background
        c = cfg.plugin_prefs[cfg.STORE_NAME]
        db = self.gui.current_db
        library_config = cfg.get_library_config(db)
        overwrite_existing = c.get(
            cfg.KEY_OVERWRITE_EXISTING,
            cfg.DEFAULT_STORE_VALUES[cfg.KEY_OVERWRITE_EXISTING],
        )
        max_tags = library_config.get(cfg.KEY_MAX_TAGS, cfg.DEFAULT_LIBRARY_VALUES[cfg.KEY_MAX_TAGS])
        prefer_html = c.get(cfg.KEY_PREFER_HTML, cfg.DEFAULT_STORE_VALUES[cfg.KEY_PREFER_HTML])

        # Run preparation job in background
        func = "arbitrary_n"
        args = [
            "calibre_plugins.romanceio_fields.jobs",
            "prepare_books_for_download",
            (book_ids, fields_to_cols_map, overwrite_existing, db.library_path),
        ]
        desc = _("Finding books on Romance.io")  # type: ignore # pylint: disable=undefined-variable
        job: CustomActionParallelJob = self.gui.job_manager.run_job(
            done=self.Dispatcher(
                partial(
                    self._preparation_completed,
                    max_tags=max_tags,
                    prefer_html=prefer_html,
                    fields_to_cols_map=fields_to_cols_map,
                )
            ),
            name=func,
            args=args,
            description=desc,
        )
        job.fields_to_cols_map = fields_to_cols_map
        job.plugin_callback = self.plugin_callback
        self.gui.status_bar.show_message(_("Finding %d books on Romance.io") % len(book_ids))  # type: ignore # pylint: disable=undefined-variable

    def _preparation_completed(
        self,
        job: CustomActionParallelJob,
        max_tags: int,
        prefer_html: bool,
        fields_to_cols_map: Dict[str, str],
    ) -> None:
        if job.failed:
            return self.gui.job_exception(job, dialog_title=_("Failed to prepare books"))  # type: ignore # pylint: disable=undefined-variable

        # Unpack results
        if job.result is None:
            return None
        result = job.result
        if isinstance(result, tuple) and len(result) == 4:
            books_to_scan_raw, warnings, errors, saved_identifiers = result
        else:
            print(f"Unexpected result format: {type(result)}, value: {result}")
            return None

        # Save identifiers in main thread so GUI sees the changes
        if saved_identifiers:
            db = self.gui.current_db
            for book_id, romanceio_id in saved_identifiers.items():
                identifiers = db.get_identifiers(book_id, index_is_id=True)
                identifiers["romanceio"] = romanceio_id
                db.set_identifiers(book_id, identifiers, notify=False, commit=True)
                print(f"Saved romanceio identifier {romanceio_id} for book {book_id}")

            # Refresh GUI
            book_ids_to_refresh = list(saved_identifiers.keys())
            print(f"Refreshing GUI for {len(book_ids_to_refresh)} books with new identifiers")
            self.gui.library_view.model().refresh_ids(book_ids_to_refresh)
            self.gui.library_view.model().refresh_ids(
                book_ids_to_refresh,
                current_row=self.gui.library_view.currentIndex().row(),
            )

        # Show any warnings/errors
        res = []
        distinct_problem_ids = {}

        for book_id, warning in warnings.items():
            if book_id not in distinct_problem_ids:
                distinct_problem_ids[book_id] = True
            title_author = self._get_title_author(book_id)
            res.append(f"{title_author} ({warning})")

        for book_id, error in errors.items():
            if book_id not in distinct_problem_ids:
                distinct_problem_ids[book_id] = True
            title_author = self._get_title_author(book_id)
            res.append(f"{title_author} ({error})")

        if len(res) > 0:
            successful_count = len(books_to_scan_raw)
            total_books = successful_count + len(distinct_problem_ids)
            if successful_count > 0:
                summary_msg = _(  # type: ignore # pylint: disable=undefined-variable
                    "Could not find Romance.io metadata for %d of %d books. "  # fmt: skip
                    "Continuing to download metadata for %d books."
                )
                print(summary_msg % (len(distinct_problem_ids), total_books, successful_count))
                print("\n".join(res))
            else:
                summary_msg = _(  # type: ignore # pylint: disable=undefined-variable
                    "Could not find Romance.io metadata for %d of %d books. "  # fmt: skip
                    "No books will be updated."
                )
                print(summary_msg % (len(distinct_problem_ids), total_books))
                print("\n".join(res))
                self.gui.status_bar.show_message(_("No books to update"), 3000)  # type: ignore # pylint: disable=undefined-variable
                return None

        # Queue the download job
        if books_to_scan_raw:
            self._queue_download_job(books_to_scan_raw, fields_to_cols_map, max_tags, prefer_html)

        return None

    def _get_title_author(self, book_id: int) -> str:
        db = self.gui.current_db
        title = db.title(book_id, index_is_id=True)
        authors = db.authors(book_id, index_is_id=True)
        if authors:
            authors = [x.replace("|", ",") for x in authors.split(",")]
            title += " - " + " & ".join([a.replace("&", "&&") for a in authors if a])
        return title

    def _queue_download_job(
        self,
        books_to_scan_raw: List[Tuple],
        fields_to_cols_map: Dict[str, str],
        max_tags: int,
        prefer_html: bool = False,
    ) -> None:
        func = "arbitrary_n"
        cpus: Optional[int] = self.gui.job_manager.server.pool_size
        args = [
            "calibre_plugins.romanceio_fields.jobs",
            "do_metadata_download",
            (books_to_scan_raw, max_tags, cpus, prefer_html),
        ]
        desc = _("Download Romance.io Fields")  # type: ignore # pylint: disable=undefined-variable
        job: CustomActionParallelJob = self.gui.job_manager.run_job(
            done=self.Dispatcher(self._get_download_completed),
            name=func,
            args=args,
            description=desc,
        )
        job.fields_to_cols_map = fields_to_cols_map
        job.plugin_callback = self.plugin_callback
        self.gui.status_bar.show_message(_("Downloading metadata for %d books") % len(books_to_scan_raw))  # type: ignore # pylint: disable=undefined-variable

    def _get_download_completed(self, job: CustomActionParallelJob) -> None:
        if job.failed:
            return self.gui.job_exception(job, dialog_title=_("Failed to download metadata"))  # type: ignore # pylint: disable=undefined-variable
        self.gui.status_bar.show_message(_("Downloading metadata completed"), 3000)  # type: ignore # pylint: disable=undefined-variable
        book_fields_map = job.result

        if book_fields_map is None or len(book_fields_map) == 0:
            # Must have been some sort of error in processing this book
            msg = _("Failed to download any metadata. <b>View Log</b> for details")  # type: ignore # pylint: disable=undefined-variable
            p = ErrorNotification(
                job.details,
                _("Romance.io log"),  # type: ignore # pylint: disable=undefined-variable
                _("Download Metadata failed"),  # type: ignore # pylint: disable=undefined-variable
                msg,
                show_copy_button=False,
                parent=self.gui,
            )
            p.show()
        else:
            payload = (job.fields_to_cols_map, book_fields_map)

            if cfg.plugin_prefs[cfg.STORE_NAME].get(
                cfg.KEY_ASK_FOR_CONFIRMATION,
                cfg.DEFAULT_STORE_VALUES[cfg.KEY_ASK_FOR_CONFIRMATION],
            ):
                all_ids = set(book_fields_map.keys())
                msg = _(  # type: ignore # pylint: disable=undefined-variable
                    "<p>Romance.io Fields plugin found <b>%d books to update</b>. "
                ) % len(
                    all_ids
                ) + _(  # type: ignore # pylint: disable=undefined-variable
                    "Proceed with updating columns in your library?"
                )
                self.gui.proceed_question(
                    self._update_database_columns,
                    payload,
                    job.details,
                    _("Romance.io log"),  # type: ignore # pylint: disable=undefined-variable
                    _("Download complete"),  # type: ignore # pylint: disable=undefined-variable
                    msg,
                    show_copy_button=False,
                )
            else:
                self._update_database_columns(payload)

        if job.plugin_callback:
            call_plugin_callback(job.plugin_callback, self.gui, plugin_results=book_fields_map)

        return None

    def _update_database_columns(self, payload: Tuple[Dict[str, str], Dict[int, Dict[str, Any]]]) -> None:
        fields_to_cols_map, book_fields_map = payload

        self.progressbar(_("Updating fields"), on_top=True)  # type: ignore # pylint: disable=undefined-variable
        total_books = len(book_fields_map)
        self.show_progressbar(total_books)
        self.set_progressbar_label(_("Updating"))  # type: ignore # pylint: disable=undefined-variable

        db = self.gui.current_db
        db_ref = db.new_api if hasattr(db, "new_api") else db
        book_ids_to_update = set()
        invalid_id_books = []

        col_name_books_map: Dict[str, Dict[int, Any]] = {
            col_name: {} for col_name in fields_to_cols_map.values() if col_name
        }

        for book_id, fields in book_fields_map.items():
            if not fields:
                # Skip if fields is None or empty (job may have failed)
                print(f"[romanceio_fields] Skipping book_id {book_id}: no fields data")
                continue

            if db_ref.has_id(book_id):
                self.set_progressbar_label(_("Updating") + " " + db_ref.field_for("title", book_id))  # type: ignore # pylint: disable=undefined-variable
                self.increment_progressbar()

                if fields.get("invalid_romanceio_id"):
                    identifiers = db.get_identifiers(book_id, index_is_id=True)
                    if cfg.ID_NAME in identifiers:
                        del identifiers[cfg.ID_NAME]
                        db.set_identifiers(book_id, identifiers, notify=False, commit=True)
                        title = db_ref.field_for("title", book_id)
                        invalid_id_books.append(title)
                    continue  # Skip processing other fields for this book

                for field, value in fields.items():
                    col_name = fields_to_cols_map.get(field)
                    if col_name is not None:
                        col_name_books_map[col_name][book_id] = value
                        book_ids_to_update.add(book_id)
            else:
                print(f"Book with id {book_id} is no longer in the library.")

        for col_name, book_fields_map in col_name_books_map.items():
            db_ref.set_field(col_name, book_fields_map)
            print(f"Updated column {col_name} for {len(book_fields_map)} books")

        if book_ids_to_update:
            book_ids_list = list(book_ids_to_update)
            print("About to refresh GUI - book_ids_to_update=", book_ids_list)
            self.gui.library_view.model().refresh_ids(book_ids_list)
            self.gui.library_view.model().refresh_ids(
                book_ids_list,
                current_row=self.gui.library_view.currentIndex().row(),
            )

        self.hide_progressbar()

        # Show message about invalid IDs if any were found
        if invalid_id_books:
            from calibre.gui2 import info_dialog

            books_str = "\n".join(f"• {title}" for title in invalid_id_books)
            msg = _(  # type: ignore # pylint: disable=undefined-variable
                "Invalid Romance.io ID(s) were removed from the following book(s):\n\n{0}\n\n"
                "These books returned 404 errors from Romance.io. "
                "The IDs have been cleared so you can search again."
            ).format(books_str)
            info_dialog(
                self.gui,
                _("Invalid IDs Removed"),  # type: ignore # pylint: disable=undefined-variable
                msg,
                show=True,
            )

    def show_configuration(self):
        assert self.interface_action_base_plugin is not None
        self.interface_action_base_plugin.do_user_config(self.gui)

    def progressbar(self, window_title, on_top=False):
        self.pb = ProgressBarDialog(parent=self.gui, window_title=window_title, on_top=on_top)
        self.pb.show()

    def show_progressbar(self, maximum_count):
        if self.pb:
            self.pb.set_maximum(maximum_count)
            self.pb.set_value(0)
            self.pb.show()

    def set_progressbar_label(self, label):
        if self.pb:
            self.pb.set_label(label)

    def increment_progressbar(self):
        if self.pb:
            self.pb.increment()

    def hide_progressbar(self):
        if self.pb:
            self.pb.hide()
