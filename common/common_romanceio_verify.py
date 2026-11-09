"""Let the user complete Romance.io's Cloudflare check in a visible browser.

The user's installed Chrome is used when available, since Cloudflare rejects
Calibre's embedded engine. The plugin never clicks or solves the check
here. The user does, and the resulting clearance is saved so lookups reuse it
until Cloudflare asks again (at most a day).
"""

import threading
import time
from urllib.parse import urlparse

# pylint: disable=duplicate-code  # Standard Calibre plugin import pattern
try:
    from qt.core import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QTimer, QUrl, QVBoxLayout, sip
    from qt.webengine import QWebEnginePage, QWebEngineProfile, QWebEngineView
except ImportError:
    # Calibre 5 uses Qt 5 and predates the qt compatibility package.
    from PyQt5 import sip
    from PyQt5.QtCore import QTimer, QUrl
    from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout
    from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile, QWebEngineView
# pylint: enable=duplicate-code

from .common_romanceio_session import CHALLENGE_SEEN, has_clearance, save_clearance
from .common_romanceio_webengine import is_challenge_title

VERIFY_URL = "https://www.romance.io/"
# Time the user has to complete the check in Chrome.
_CHROME_VERIFY_SECONDS = 300
# The fetch helper only uses its isolated worker from the installed plugin package.
_PLUGIN_NAME = __name__.split(".")[1] if __name__.startswith("calibre_plugins.") else "romanceio_fields"


class ChromeVerifyDialog(QDialog):
    """Open Romance.io in the user's Chrome and wait while they complete the check."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Verify Romance.io access"))  # type: ignore # pylint: disable=undefined-variable
        self.verified = False
        self.chrome_missing = False
        self.messages = []
        self.outcome = {}
        self.abort = threading.Event()
        self.started = time.monotonic()
        layout = QVBoxLayout(self)
        intro = QLabel(
            _(  # type: ignore # pylint: disable=undefined-variable
                "A Chrome window is opening on Romance.io. Romance.io uses a Cloudflare check to tell people "
                'from automated traffic. Cloudflare may show "Just a moment..." for a minute or two before it '
                "continues; leave the window open, and if a checkbox appears, complete it there. You can use the "
                "window normally. Chrome closes once Romance.io loads, and lookups reuse the verification until "
                "Romance.io asks again."
            ),
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.status = QLabel(_("Starting Chrome..."), self)  # type: ignore # pylint: disable=undefined-variable
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        # Shown only if verification does not finish, so the cause is visible.
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        layout.addWidget(self.details, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.resize(520, 180)
        threading.Thread(target=self._run, daemon=True).start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(200)

    def _run(self):
        from .common_romanceio_fetch_helper import fetch_page

        try:
            fetch_page(
                VERIFY_URL,
                _PLUGIN_NAME,
                max_wait=_CHROME_VERIFY_SECONDS,
                log_func=self.messages.append,
                abort=self.abort,
                backend="chrome",
                interactive=True,
            )
            self.outcome["page"] = True
        except Exception as error:  # pylint: disable=broad-except
            self.outcome["error"] = str(error)

    def _poll(self):
        if any(CHALLENGE_SEEN in str(message) for message in self.messages):
            elapsed = int(time.monotonic() - self.started)
            self.status.setText(
                _("Waiting for Cloudflare's check in the Chrome window (%d:%02d)...")  # type: ignore # pylint: disable=undefined-variable
                % divmod(elapsed, 60)
            )
        if not self.outcome or self.abort.is_set():
            return
        self.timer.stop()
        # Chrome had the focus; bring Calibre back for the result.
        self.raise_()
        self.activateWindow()
        if self.outcome.get("page"):
            self.verified = True
            if has_clearance():
                self.status.setText(_("Verified. Romance.io lookups can continue."))  # type: ignore # pylint: disable=undefined-variable
            else:
                self.status.setText(
                    _(  # type: ignore # pylint: disable=undefined-variable
                        "Romance.io loaded without asking for a check, so no verification is needed right now."
                    )
                )
            QTimer.singleShot(1500, self.accept)
            return
        error = self.outcome.get("error", "")
        if "chrome not found" in error.lower() or "install it first" in error.lower():
            self.chrome_missing = True
            self.reject()
            return
        self.status.setText(
            _("Verification did not finish: %s") % error  # type: ignore # pylint: disable=undefined-variable
        )
        self.details.setPlainText("\n".join(str(message) for message in self.messages))
        self.details.setVisible(True)
        self.resize(self.width(), 420)
        self.buttons.setStandardButtons(QDialogButtonBox.Close)

    def done(self, result):  # pylint: disable=invalid-name
        # Cancelling stops Chrome; its worker finishes cleanup in the background.
        if not self.outcome:
            self.abort.set()
        self.timer.stop()
        super().done(result)


class _VerifyPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _kind, is_main_frame):  # pylint: disable=invalid-name
        parsed = urlparse(url.toString())
        if not is_main_frame:
            # Cloudflare's check runs in its own HTTPS frame.
            return parsed.scheme in ("https", "about", "blob", "data")
        return parsed.scheme == "https" and parsed.hostname == "www.romance.io"


class VerifyAccessDialog(QDialog):
    """Without Chrome, show Romance.io in Calibre's engine until the user's check succeeds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Verify Romance.io access"))  # type: ignore # pylint: disable=undefined-variable
        self.verified = False
        self._closed = False
        self.cookies = []
        layout = QVBoxLayout(self)
        intro = QLabel(
            _(  # type: ignore # pylint: disable=undefined-variable
                "Romance.io uses a Cloudflare check to tell people from automated traffic. "
                "If a checkbox appears below, complete it. This window closes once Romance.io loads, "
                "and lookups reuse the verification until Romance.io asks again."
            ),
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        # Off-the-record, like background lookups: nothing but the clearance is kept.
        self.profile = QWebEngineProfile(self)
        self.profile.cookieStore().cookieAdded.connect(self._cookie_added)
        self.page = _VerifyPage(self.profile, self)
        self.page.titleChanged.connect(lambda _title: self._check())
        self.page.loadFinished.connect(self._load_finished)
        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        layout.addWidget(self.view, 1)
        self.status = QLabel(_("Loading Romance.io..."), self)  # type: ignore # pylint: disable=undefined-variable
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(900, 720)
        self.view.load(QUrl(VERIFY_URL))

    def _cookie_added(self, cookie):
        if bytes(cookie.name()) != b"cf_clearance":
            return
        self.cookies = [
            {
                "name": "cf_clearance",
                "value": bytes(cookie.value()).decode("ascii", errors="replace"),
                "domain": cookie.domain(),
                "expiry": cookie.expirationDate().toSecsSinceEpoch(),
            }
        ]
        self._check()

    def _on_romanceio(self):
        current = urlparse(self.page.url().toString())
        return current.scheme == "https" and current.hostname == "www.romance.io"

    def _check(self):
        if self._closed or self.verified or not self.cookies:
            return
        if is_challenge_title(self.page.title()) or not self._on_romanceio():
            return
        if save_clearance(self.cookies, self.profile.httpUserAgent()):
            self.verified = True
            self.status.setText(
                _("Verified. Romance.io lookups can continue.")  # type: ignore # pylint: disable=undefined-variable
            )
            QTimer.singleShot(1500, self.accept)
        else:
            self.status.setText(
                _("Romance.io loaded, but its verification could not be saved.")  # type: ignore # pylint: disable=undefined-variable
            )

    def _load_finished(self, ok):
        self._check()
        if self._closed or self.verified:
            return
        if is_challenge_title(self.page.title()):
            # Qt reports the check's HTTP 403 as a failed load.
            self.status.setText(_("Waiting for Romance.io's check..."))  # type: ignore # pylint: disable=undefined-variable
        elif not ok:
            self.status.setText(
                _("Romance.io could not be loaded. Check your connection and try again.")  # type: ignore # pylint: disable=undefined-variable
            )
        elif not is_challenge_title(self.page.title()) and not self.cookies:
            self.status.setText(
                _(  # type: ignore # pylint: disable=undefined-variable
                    "Romance.io loaded without asking for a check, so no verification is needed right now."
                )
            )

    def done(self, result):  # pylint: disable=invalid-name
        # The auto-close timer and the Close button can both arrive.
        if self._closed:
            return
        self._closed = True
        # Delete the page before its profile, as Qt WebEngine requires.
        sip.delete(self.view)
        sip.delete(self.page)
        sip.delete(self.profile)
        super().done(result)


def _run_dialog(dialog):
    execute = getattr(dialog, "exec", None) or dialog.exec_
    execute()
    return dialog


def verify_romanceio_access(parent=None, log=None):
    """Return True once Romance.io loads after the user's check, so lookups can retry.

    The verification's progress messages are appended to log, if given.
    """
    chrome = _run_dialog(ChromeVerifyDialog(parent))
    if log is not None:
        log.extend(str(message) for message in chrome.messages)
    if not chrome.chrome_missing:
        return chrome.verified
    if log is not None:
        log.append("Chrome is not installed; verifying in Calibre's built-in browser")
    return _run_dialog(VerifyAccessDialog(parent)).verified
