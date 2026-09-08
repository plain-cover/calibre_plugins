# Maintain backwards compatibility with older versions of Qt and calibre.
try:
    from qt.core import QSizePolicy, QTextEdit, Qt
except ImportError:
    from PyQt5.Qt import QSizePolicy, QTextEdit, Qt

try:
    qSizePolicy_Minimum = QSizePolicy.Policy.Minimum
    qSizePolicy_Maximum = QSizePolicy.Policy.Maximum
    qSizePolicy_Expanding = QSizePolicy.Policy.Expanding
    qSizePolicy_Preferred = QSizePolicy.Policy.Preferred
    qSizePolicy_Ignored = QSizePolicy.Policy.Ignored
except AttributeError:
    qSizePolicy_Minimum = QSizePolicy.Minimum
    qSizePolicy_Maximum = QSizePolicy.Maximum
    qSizePolicy_Expanding = QSizePolicy.Expanding
    qSizePolicy_Preferred = QSizePolicy.Preferred
    qSizePolicy_Ignored = QSizePolicy.Ignored

try:
    qTextEdit_NoWrap = QTextEdit.LineWrapMode.NoWrap
except AttributeError:
    qTextEdit_NoWrap = QTextEdit.NoWrap

try:
    qtDropActionCopyAction = Qt.DropAction.CopyAction
    qtDropActionMoveAction = Qt.DropAction.MoveAction
except AttributeError:
    qtDropActionCopyAction = Qt.CopyAction
    qtDropActionMoveAction = Qt.MoveAction

# Shared tooltip for the "prefer HTML" checkbox, used by both romanceio and romanceio_fields.
# Must be wrapped with _() at the call site so Calibre's translation system handles it at runtime.
PREFER_HTML_TOOLTIP = (
    "With this option checked, the plugin tries Chrome first. Unchecked, "
    "it first tries to download the book’s details and tags without a browser, "
    "then uses a browser if needed."
)
