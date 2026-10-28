"""Load a trivial page in Calibre's Qt WebEngine without any plugin browser setup.

Temporary diagnostic for the Calibre 5.44 renderer access violation on Windows.
Prints GitHub annotations so results are visible without downloading job logs.
"""

import os
import sys
from typing import Any, Dict

MARKER = "diag-qt-webengine-ok"


def _annotation(level, title, message):
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level} title={title}::{message}", flush=True)


def main():
    title = os.environ.get("DIAG_TITLE", "Qt minimal repro")
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    # Match the plugin's software rendering; Calibre's headless platform has no OpenGL.
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()
    print(f"QTWEBENGINE_CHROMIUM_FLAGS={os.environ['QTWEBENGINE_CHROMIUM_FLAGS']}", flush=True)
    from calibre.gui2 import must_use_qt

    try:
        from qt.core import PYQT_VERSION_STR, QT_VERSION_STR, QApplication, QTimer, QUrl
        from qt.webengine import QWebEnginePage, QWebEngineProfile
    except ImportError:
        from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QTimer, QUrl
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile

    must_use_qt()
    app = QApplication.instance()
    user_agent = QWebEngineProfile.defaultProfile().httpUserAgent()
    versions = f"Qt {QT_VERSION_STR}, PyQt {PYQT_VERSION_STR}, Python {sys.version.split()[0]}; UA: {user_agent}"
    print(versions, flush=True)
    page = QWebEnginePage(app)
    result: Dict[str, Any] = {}

    def done(**values):
        if not result:
            result.update(values)
            app.quit()

    page.renderProcessTerminated.connect(
        lambda status, exit_code: done(error=f"renderer exited (status={status}, exit code={exit_code})")
    )
    page.loadFinished.connect(lambda ok: page.toHtml(lambda html: done(ok=ok, html=html)))
    QTimer.singleShot(20000, lambda: done(error="timed out after 20s"))
    QTimer.singleShot(0, lambda: page.load(QUrl(f"data:text/html,<p>{MARKER}</p>")))
    execute = getattr(app, "exec", None) or app.exec_
    execute()

    flags_used = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
    if result.get("error") or MARKER not in (result.get("html") or ""):
        detail = result.get("error") or f"loadFinished ok={result.get('ok')} without the marker"
        _annotation("error", title, f"FAILED: {detail}\nflags: {flags_used}\n{versions}")
        sys.exit(1)
    _annotation("notice", title, f"PASSED\nflags: {flags_used}\n{versions}")


if __name__ == "__main__":
    main()
