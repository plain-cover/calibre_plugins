from typing import Tuple, cast, Callable, Optional, Any

from calibre.gui2.actions import menu_action_unique_name
from calibre.constants import numeric_version as calibre_version

# Import get_icon - this will work once the file is copied into each plugin
get_icon: Optional[Callable[[str], Any]]
try:
    from .common_icons import get_icon  # type: ignore[import,assignment]
except ImportError:
    # Fallback during linting when file is in common/ folder
    get_icon = None

# Track registered menu actions for proper cleanup
_registered_menu_actions: list = []


def unregister_menu_actions(ia):
    """Unregister all tracked menu actions and their keyboard shortcuts.

    This is essential for Romance.io plugins that rebuild menus dynamically,
    ensuring clean removal of shortcuts before menu reconstruction.

    Note:
        Call this method before clearing menu items to prevent orphaned shortcuts.
    """
    for action in _registered_menu_actions:
        if hasattr(action, "calibre_shortcut_unique_name"):
            ia.gui.keyboard.unregister_shortcut(action.calibre_shortcut_unique_name)
        # Calibre 2.10.0+ registers actions at top GUI level for macOS
        if cast(Tuple[int, int, int], calibre_version) >= (2, 10, 0):
            ia.gui.removeAction(action)
    _registered_menu_actions.clear()


def create_menu_action_unique(
    ia,
    parent_menu,
    menu_text,
    image=None,
    tooltip=None,
    shortcut=None,
    triggered=None,
    is_checked=None,
    shortcut_name=None,
    unique_name=None,
    favourites_menu_unique_name=None,
):
    """Create a menu action compatible across calibre versions.

    Creates menu actions that properly integrate with calibre's keyboard shortcut
    system, ensuring they appear in Preferences -> Keyboard regardless of whether
    a shortcut is explicitly specified. Handles version differences in calibre's
    persist_shortcut parameter (5.4.0+).

    Note:
        This function automatically tracks created actions for proper cleanup.
    """
    orig_shortcut = shortcut
    kb = ia.gui.keyboard
    if unique_name is None:
        unique_name = menu_text
    if shortcut is not False:
        full_unique_name = menu_action_unique_name(ia, unique_name)
        if full_unique_name in kb.shortcuts:
            shortcut = False
        else:
            if shortcut is not None and shortcut is not False:
                if len(shortcut) == 0:
                    shortcut = None

    if shortcut_name is None:
        shortcut_name = menu_text.replace("&", "")

    if cast(Tuple[int, int, int], calibre_version) >= (5, 4, 0):
        # The persist_shortcut parameter only added from 5.4.0 onwards.
        # Used so that shortcuts specific to other libraries aren't discarded.
        ac = ia.create_menu_action(
            parent_menu,
            unique_name,
            menu_text,
            icon=None,
            shortcut=shortcut,
            description=tooltip,
            triggered=triggered,
            shortcut_name=shortcut_name,
            persist_shortcut=True,
        )
    else:
        ac = ia.create_menu_action(
            parent_menu,
            unique_name,
            menu_text,
            icon=None,
            shortcut=shortcut,
            description=tooltip,
            triggered=triggered,
            shortcut_name=shortcut_name,
        )
    if shortcut is False and orig_shortcut is not False:
        if ac.calibre_shortcut_unique_name in ia.gui.keyboard.shortcuts:
            kb.replace_action(ac.calibre_shortcut_unique_name, ac)
    if image and get_icon:
        ac.setIcon(get_icon(image))
    if is_checked is not None:
        ac.setCheckable(True)
        if is_checked:
            ac.setChecked(True)
    # Support Favourites Menu plugin integration with constant identifiers
    if favourites_menu_unique_name:
        ac.favourites_menu_unique_name = favourites_menu_unique_name

    # Track action for proper cleanup when menus are rebuilt
    _registered_menu_actions.append(ac)
    return ac


def create_menu_item(
    ia,
    parent_menu,
    menu_text,
    image=None,
    tooltip=None,
    shortcut=(),
    triggered=None,
    is_checked=None,
):
    """
    Create a menu action with the specified criteria and action
    Note that if no shortcut is specified, will not appear in Preferences->Keyboard
    This method should only be used for actions which either have no shortcuts,
    or register their menus only once. Use create_menu_action_unique for all else.

    Currently this function is only used by open_with and search_the_internet plugins
    and would like to investigate one day if it can be removed from them.
    """
    if shortcut is not None:
        if len(shortcut) == 0:
            shortcut = ()
    ac = ia.create_action(spec=(menu_text, None, tooltip, shortcut), attr=menu_text)
    if image and get_icon:
        ac.setIcon(get_icon(image))
    if triggered is not None:
        ac.triggered.connect(triggered)
    if is_checked is not None:
        ac.setCheckable(True)
        if is_checked:
            ac.setChecked(True)

    parent_menu.addAction(ac)
    _registered_menu_actions.append(ac)
    return ac
