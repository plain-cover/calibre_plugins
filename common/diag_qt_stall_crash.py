"""Load a never-responding page in Calibre's Qt WebEngine without any plugin code.

Temporary diagnostic for the intermittent browser-process segfault in the
embedded-engine timeout test on Linux and macOS (current Calibre, Qt 6). Each
process does one load, like the plugin's disposable browser worker:

calibre-debug -e common/diag_qt_stall_crash.py -- poll|nopoll

"poll" reads the page with toHtml() every 250 ms, as the plugin does while it
waits for content; "nopoll" only waits.
"""

import argparse
import faulthandler
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=("poll", "nopoll"))
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    faulthandler.enable()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # pylint: disable=invalid-name
            release.wait(60)
            self.close_connection = True

        def log_message(self, *_args):
            pass

    class Server(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            pass

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Same flags the plugin's embedded engine adds.
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        flags + " --disable-gpu --force-webrtc-ip-handling-policy=disable_non_proxied_udp --disable-quic"
    ).strip()
    from calibre.gui2 import must_use_qt
    from qt.core import QApplication, QTimer, QUrl, sip
    from qt.webengine import QWebEnginePage, QWebEngineProfile

    must_use_qt()
    app = QApplication.instance()
    app.setQuitOnLastWindowClosed(False)
    profile = QWebEngineProfile(app)  # Off-the-record, like the plugin.
    page = QWebEnginePage(profile, app)
    timer = QTimer(app)
    state: Dict[str, Any] = {"pending": False, "polls": 0, "error": None}

    def received(_html):
        state["pending"] = False

    def poll():
        if args.variant == "poll" and not state["pending"]:
            state["pending"] = True
            state["polls"] += 1
            page.toHtml(received)

    def renderer_exited(status, exit_code):
        state["error"] = f"renderer exited (status={status}, exit code={exit_code})"
        app.quit()

    try:
        page.renderProcessTerminated.connect(renderer_exited)
        timer.timeout.connect(poll)
        timer.start(250)
        url = f"http://127.0.0.1:{server.server_port}/stall"
        QTimer.singleShot(0, lambda: page.load(QUrl(url)))
        QTimer.singleShot(int(args.seconds * 1000), app.quit)
        print(f"{args.variant}: loading {url} for {args.seconds:g}s", flush=True)
        app.exec()
    finally:
        timer.stop()
        sip.delete(page)
        sip.delete(profile)
        release.set()
        server.shutdown()
        server.server_close()
    if state["error"]:
        print(state["error"], flush=True)
        sys.exit(2)
    print(f"{args.variant}: survived ({state['polls']} toHtml calls)", flush=True)


if __name__ == "__main__":
    main()
