"""Invisible challenge navigation using the web engine bundled with Calibre.

Run only inside the disposable, supervised browser worker. No QWebEngineView,
Chrome executable, driver download, or Selenium imports are needed.
"""

import json
import os
import time
from html.parser import HTMLParser
from urllib.parse import urlparse
from typing import Any, Dict, List

_NOT_FOUND = "the page you are looking for can't be found"


def browser_requests(request):
    """Two search routes share one profile and one engine deadline."""
    routes = [request]
    if request.get("search_fallback_url"):
        routes.append(
            {
                **request,
                "url": request["search_fallback_url"],
                "wait_for_element": "book-results",
                "secondary_wait_element": "has-background",
            }
        )
    return routes


def page_failure(html, request):
    """Return a terminal route failure, distinct from a still-loading page."""
    if urlparse(request["url"]).path.startswith("/json/"):
        if _NOT_FOUND in html.lower():
            return "JSON endpoint returned a not-found HTML page"
        parser = _JsonText()
        parser.feed(html)
        try:
            data = json.loads("".join(parser.parts))
        except (ValueError, TypeError):
            return None
        if urlparse(request["url"]).path == "/json/search_books" and not (
            isinstance(data, dict)
            and data.get("success") is True
            and isinstance(data.get("books"), list)
            and all(isinstance(book, dict) for book in data["books"])
        ):
            return "JSON search returned an invalid response contract"
    return None


def clearance_page_valid(html, request):
    return bool(html and _NOT_FOUND not in html.lower() and not page_failure(html, request))


def navigate_chrome(driver, request, log):
    """Navigate alternate search routes without restarting Chrome."""
    from .common_romanceio_fetch_helper import BrowserFetchError

    routes = browser_requests(request)
    deadline = time.monotonic() + request.get("max_wait", 30)
    for index, route in enumerate(routes):
        route_deadline = time.monotonic() + max(0, deadline - time.monotonic()) / (len(routes) - index)
        budget = route_deadline - time.monotonic()
        if budget <= 0:
            break
        driver.set_page_load_timeout(min(30, budget))
        driver.set_script_timeout(min(30, budget))
        log(f"Navigating Chrome to {route['url']}")
        try:
            driver.uc_open_with_reconnect(route["url"], reconnect_time=1)
            while time.monotonic() < route_deadline:
                html = driver.page_source
                error = page_failure(html, route)
                if error:
                    log(error)
                    break
                if page_ready(html, driver.title, route):
                    log(f"Chrome page validated ({len(html)} characters)")
                    return html
                time.sleep(0.25)
        except Exception as error:
            log(f"Chrome navigation failed ({type(error).__name__})")
        if index + 1 < len(routes):
            log("Chrome JSON route failed; trying HTML search in the same browser session")
    raise BrowserFetchError("Chrome did not return validated content within its navigation budget")


class _JsonText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def page_ready(html, title, request):
    """Distinguish challenge/partial documents from usable JSON and HTML."""
    if not html or len(html) < 100:
        return False
    if any(text in title.lower() for text in ("just a moment", "checking your browser", "verifying you are human")):
        return False
    if page_failure(html, request):
        return False
    if urlparse(request["url"]).path.startswith("/json/"):
        parser = _JsonText()
        parser.feed(html)
        try:
            return isinstance(json.loads("".join(parser.parts)), (dict, list))
        except (ValueError, TypeError):
            return False
    marker = request.get("not_found_marker")
    if marker and marker.lower() in html.lower():
        return True
    required = request.get("wait_for_element")
    if required == "book-results":
        # Inspect actual nodes, not selector strings inside scripts/templates.
        from lxml.html import fromstring

        return bool(fromstring(html).xpath('//ul[@id="book-results"]//li[@class="has-background"]'))
    return required in html if required else "</body>" in html.lower()


def fetch_page(request, log):
    """Return rendered HTML, with navigation and shutdown covered by supervision."""
    # WebRTC ICE/STUN can bind UDP sockets and trigger Windows Firewall prompts.
    # Apply Qt's supported Chromium policy before initializing the engine. Normal
    # HTTPS downloads need neither peer-to-peer networking nor QUIC.
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        flags + " --force-webrtc-ip-handling-policy=disable_non_proxied_udp --disable-quic"
    ).strip()
    from calibre.gui2 import must_use_qt

    try:
        from qt.core import QApplication, QTimer, QUrl, sip
        from qt.webengine import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    except ImportError:
        # Calibre 5 uses Qt 5 and predates the qt compatibility package.
        from PyQt5 import sip
        from PyQt5.QtCore import QTimer, QUrl
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile, QWebEngineSettings

    from .common_romanceio_fetch_helper import BrowserFetchError
    from .common_romanceio_session import save_clearance

    must_use_qt()
    app = QApplication.instance()
    app.setQuitOnLastWindowClosed(False)
    log("Starting Calibre embedded web engine (no browser window)")
    profile = QWebEngineProfile(app)  # Off-the-record: no persistent browser profile.
    settings = profile.settings()
    attributes = getattr(QWebEngineSettings, "WebAttribute", QWebEngineSettings)
    for name in (
        "JavascriptCanOpenWindows",
        "JavascriptCanAccessClipboard",
        "LocalContentCanAccessFileUrls",
        "LocalContentCanAccessRemoteUrls",
        "AllowWindowActivationFromJavaScript",
    ):
        if hasattr(attributes, name):
            settings.setAttribute(getattr(attributes, name), False)
    origin = urlparse(request["url"])

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, *_args):
            # Site console output may contain cookies/challenge tokens.
            pass

        def javaScriptAlert(self, *_args):
            pass

        def javaScriptConfirm(self, *_args):
            return False

        def javaScriptPrompt(self, *_args):
            return False, ""

        def acceptNavigationRequest(self, url, _kind, is_main_frame):
            parsed = urlparse(url.toString())
            if parsed.scheme not in ("http", "https"):
                return False
            return not is_main_frame or (parsed.scheme, parsed.netloc) == (origin.scheme, origin.netloc)

    page = Page(profile, app)
    timer = QTimer(app)
    started = time.monotonic()
    deadline = started + request.get("max_wait", 30)
    routes = browser_requests(request)
    route_deadline = started + request.get("max_wait", 30) / len(routes)
    state: Dict[str, Any] = {
        "done": False,
        "pending": False,
        "html": None,
        "candidate": None,
        "ready_since": None,
        "error": None,
        "title": None,
        "route": 0,
    }
    cookies: List[Dict[str, Any]] = []

    def cookie_added(cookie):
        if bytes(cookie.name()) == b"cf_clearance":
            cookies[:] = [
                {
                    "name": "cf_clearance",
                    "value": bytes(cookie.value()).decode("ascii", errors="replace"),
                    "domain": cookie.domain(),
                    "expiry": cookie.expirationDate().toSecsSinceEpoch(),
                }
            ]

    def finish(html=None, error=None):
        state.update(done=True, html=html, error=error)
        app.quit()

    def advance(error):
        nonlocal request, route_deadline
        if state["route"] + 1 >= len(routes) or time.monotonic() >= deadline:
            finish(error=error)
            return
        state["route"] += 1
        request = routes[state["route"]]
        state.update(pending=False, candidate=None, ready_since=None, title=None)
        route_deadline = deadline
        log(f"{error}; trying HTML search in the same embedded browser session")
        page.load(QUrl(request["url"]))

    def inspect(html, generation):
        if generation != state["route"]:
            return
        state["pending"] = False
        if state["done"]:
            return
        try:
            title = page.title()
            if title != state["title"]:
                # Do not echo untrusted titles that could contain challenge tokens.
                log("Embedded web engine: checking page content")
                state["title"] = title
            failure = page_failure(html, request)
            if failure:
                advance(failure)
                return
            if not page_ready(html, title, request):
                state.update(candidate=None, ready_since=None)
                return
            state["candidate"] = html
            now = time.monotonic()
            if state["ready_since"] is None:
                state["ready_since"] = now
            marker = request.get("not_found_marker")
            missing = marker and marker.lower() in html.lower()
            secondary = request.get("secondary_wait_element")
            if missing or ((not secondary or secondary in html) and now - state["ready_since"] >= 1):
                finish(html=html)
        except Exception as error:  # Qt callbacks must not escape into the event loop.
            finish(error=f"Embedded page inspection failed: {type(error).__name__}")

    def poll():
        if state["done"]:
            return
        if time.monotonic() >= route_deadline:
            if state["candidate"]:
                finish(html=state["candidate"])
            else:
                advance("Embedded web engine timed out waiting for validated content or Cloudflare clearance")
        elif not state["pending"]:
            state["pending"] = True
            generation = state["route"]
            page.toHtml(lambda html: inspect(html, generation))

    try:
        profile.cookieStore().cookieAdded.connect(cookie_added)
        page.renderProcessTerminated.connect(
            lambda *_args: finish(error="Embedded web engine renderer exited unexpectedly")
        )
        timer.timeout.connect(poll)
        timer.start(250)
        log(f"Navigating embedded web engine to {request['url']}")
        page.load(QUrl(request["url"]))
        execute = getattr(app, "exec", None) or app.exec_
        execute()
        if state["error"] or not state["html"]:
            raise BrowserFetchError(state["error"] or "Embedded web engine returned no page")
        if (
            origin.scheme == "https"
            and origin.hostname == "www.romance.io"
            and clearance_page_valid(state["html"], request)
        ):
            try:
                if save_clearance(cookies, profile.httpUserAgent()):
                    log("Saved temporary Cloudflare clearance; subsequent requests can use direct HTTP")
            except Exception as error:
                log(f"Could not save browser clearance ({type(error).__name__})")
        log(f"Embedded page loaded successfully ({len(state['html'])} characters)")
        return state["html"]
    finally:
        state["done"] = True
        timer.stop()
        log("Closing embedded web engine")
        sip.delete(page)
        sip.delete(profile)
        log("Embedded web engine closed")
