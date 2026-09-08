"""Exercise installed Qt or Chrome rendering and cleanup against a local page."""

import argparse
import importlib
import os
import shutil
import stat
import sys
import tempfile
import threading
from unittest.mock import patch
from typing import List
from http.server import BaseHTTPRequestHandler, HTTPServer

PLUGINS = {
    "romanceio": "Romance.io",
    "romanceio_fields": "Romance.io Fields",
}


class _LocalPageHandler(BaseHTTPRequestHandler):
    body = b""
    search_routes = False
    paths: List[str] = []

    def do_GET(self):  # pylint: disable=invalid-name
        self.paths.append(self.path)
        if self.path == "/challenge":
            body = b"<html><title>Just a moment</title><body>Challenge</body></html>" + b" " * 100
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        missing = self.search_routes and self.path.startswith("/json/")
        body = (
            b"<html><body>The page you are looking for can't be found</body></html>" + b" " * 100
            if missing
            else self.body
        )
        self.send_response(404 if missing else 200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin,unused-argument
        return


class _QuietHTTPServer(HTTPServer):
    def handle_error(self, request, client_address):  # pylint: disable=unused-argument
        return


def _find_runner_chromedriver():
    configured = os.environ.get("CHROMEWEBDRIVER", "")
    candidates = []
    if configured:
        candidates.append(configured)
        candidates.extend(os.path.join(configured, name) for name in ("chromedriver", "chromedriver.exe"))
    candidates.extend(filter(None, (shutil.which("chromedriver"), shutil.which("chromedriver.exe"))))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    raise AssertionError(f"GitHub runner ChromeDriver was not found; CHROMEWEBDRIVER={configured!r}")


def _seed_production_driver(source):
    stable_base = os.environ.get("CALIBRE_SELENIUM_HOME") or os.path.join(os.path.expanduser("~"), ".calibre_selenium")
    driver_dir = os.path.join(stable_base, "drivers")
    os.makedirs(driver_dir, exist_ok=True)
    filename = "chromedriver.exe" if os.name == "nt" else "chromedriver"
    destination = os.path.join(driver_dir, filename)
    if os.path.normcase(os.path.abspath(source)) != os.path.normcase(os.path.abspath(destination)):
        shutil.copy2(source, destination)
    if os.name != "nt":
        os.chmod(destination, os.stat(destination).st_mode | stat.S_IXUSR)
    return destination


def _prepare_driver(driver_source):
    """Seed the runner driver or exercise the plugin's managed download path."""
    if driver_source == "managed":
        print("No ChromeDriver seeded; exercising the plugin's managed driver download")
        return None

    source_driver = _find_runner_chromedriver()
    seeded_driver = _seed_production_driver(source_driver)
    print(f"Seeded matching runner ChromeDriver: {source_driver} -> {seeded_driver}")
    return seeded_driver


def _verify_flatpak_chrome(helper):
    """Require the installed plugin to see a directly runnable Flatpak Chrome."""
    if not os.environ.get("FLATPAK_ID"):
        raise AssertionError("--require-flatpak-chrome must run inside a Flatpak sandbox")
    chrome_path = helper._find_flatpak_chrome()  # pylint: disable=protected-access
    if not chrome_path:
        raise AssertionError("Installed plugin could not find a directly runnable Flatpak Chrome binary")
    print(f"Detected directly runnable Flatpak Chrome: {chrome_path}")
    return chrome_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", choices=sorted(PLUGINS))
    parser.add_argument("--backend", choices=("embedded", "chrome"), default="embedded")
    parser.add_argument("--driver-source", choices=("runner", "managed"), default="runner")
    parser.add_argument("--require-flatpak-chrome", action="store_true")
    parser.add_argument("--search-routes", action="store_true", help="Recover JSON 404 via HTML in one browser session")
    parser.add_argument("--failure-first", action="store_true", help="Fail a challenge, then verify two fresh lookups")
    parser.add_argument(
        "--chrome-fallback",
        action="store_true",
        help="Simulate embedded failure, then exercise the real optional Chrome worker",
    )
    args = parser.parse_args()
    if args.failure_first and args.chrome_fallback:
        parser.error("--failure-first tests one engine; do not combine with --chrome-fallback")
    chrome = args.backend == "chrome" or args.chrome_fallback
    if args.chrome_fallback and args.backend == "chrome":
        parser.error("--chrome-fallback simulates Qt failure; use it without --backend chrome")
    if args.require_flatpak_chrome and not chrome:
        parser.error("--require-flatpak-chrome requires a Chrome test")

    from calibre.customize.ui import find_plugin

    display_name = PLUGINS[args.plugin]
    plugin = find_plugin(display_name)
    if plugin is None:
        raise AssertionError(f"{display_name} is not installed")

    smoke_parent = os.environ.get("RUNNER_TEMP") or os.environ.get("CALIBRE_CONFIG_DIRECTORY") or tempfile.gettempdir()
    os.environ["CALIBRE_SELENIUM_HOME"] = os.path.join(smoke_parent, "browser-smoke", args.plugin)

    helper = importlib.import_module(f"calibre_plugins.{args.plugin}.common_romanceio_fetch_helper")
    if chrome:
        if args.require_flatpak_chrome:
            _verify_flatpak_chrome(helper)
        _prepare_driver(args.driver_source)

    marker = "calibre-installed-plugin-browser-smoke-pass"
    html = f"""<html><body><p>{'local fixture ' * 20}</p><script>
    alert('must not display'); confirm('must not display'); prompt('must not display');
    var pc = new RTCPeerConnection({{iceServers: []}});
    pc.createDataChannel('network-check');
    pc.createOffer().then(function(offer) {{ return pc.setLocalDescription(offer); }});
    setTimeout(function() {{ document.body.insertAdjacentHTML('beforeend', '<h1>{marker}</h1>'); }}, 1500);
    </script></body></html>"""
    if chrome:
        html = f"""<html><body><p>{'local fixture ' * 20}</p><script>
        setTimeout(function() {{ document.body.insertAdjacentHTML('beforeend', '<h1>{marker}</h1>'); }}, 1500);
        </script></body></html>"""
    real_fetch = helper._fetch_page_via_calibre_worker
    if args.search_routes:
        html = html.replace(
            f"<h1>{marker}</h1>", f'<ul id="book-results"><li class="has-background">{marker}</li></ul>'
        )
    _LocalPageHandler.search_routes = args.search_routes
    _LocalPageHandler.paths = []
    attempts = []

    def checked_fetch(request, log, abort):
        backend = request.get("backend", "embedded")
        attempts.append(backend)
        if backend == "embedded" and args.chrome_fallback:
            raise helper.BrowserFetchError("TEST: simulated embedded-engine failure")
        assert backend == args.backend or args.chrome_fallback, "Unexpected browser fallback in backend-only test"
        return real_fetch(request, log, abort)

    _LocalPageHandler.body = html.encode("utf-8")
    server = _QuietHTTPServer(("127.0.0.1", 0), _LocalPageHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    import psutil

    check_sockets = sys.platform != "darwin" and not chrome
    if sys.platform == "darwin":
        print("Socket inspection skipped: macOS requires elevated privileges for psutil networking")
    owner = psutil.Process()
    stopped = threading.Event()
    tracked = set()
    violations = set()

    def monitor():
        while not stopped.is_set():
            try:
                tracked.update(owner.children(recursive=True))
                for process in list(tracked):
                    try:
                        if not chrome and process.name().lower() in (
                            "chrome.exe",
                            "chrome",
                            "google chrome",
                            "chromedriver",
                            "chromedriver.exe",
                            "uc_driver.exe",
                        ):
                            violations.add("External Chrome process launched")
                        connections = getattr(process, "net_connections", None) or process.connections
                        for connection in connections(kind="inet") if check_sockets else ():
                            if connection.type == 2:
                                violations.add("Browser worker opened UDP socket")
                            if connection.status == "LISTEN" and connection.laddr.ip not in ("127.0.0.1", "::1"):
                                violations.add("Browser worker opened non-loopback TCP listener")
                    except psutil.NoSuchProcess:
                        pass
            except psutil.Error as error:
                violations.add("Could not inspect browser networking: " + type(error).__name__)
            stopped.wait(0.05)

    observer = threading.Thread(target=monitor, daemon=True)
    observer.start()
    try:
        local_url = f"http://127.0.0.1:{server.server_port}/browser-smoke"
        if args.search_routes:
            local_url = f"http://127.0.0.1:{server.server_port}/json/search_books?search=test"
        with patch.object(helper, "_fetch_page_via_calibre_worker", checked_fetch):
            if args.failure_first:
                try:
                    helper.fetch_page(
                        f"http://127.0.0.1:{server.server_port}/challenge",
                        args.plugin,
                        max_wait=2,
                        log_func=print,
                        backend=args.backend,
                    )
                except helper.BrowserFetchError:
                    print("PASS: challenge failed explicitly; testing subsequent lookups in the same caller")
                else:
                    raise AssertionError("Challenge was incorrectly accepted")
            for _ in range(2 if args.failure_first else 1):
                page = helper.fetch_page(
                    local_url,
                    args.plugin,
                    wait_for_element="<h1>" + marker + "</h1>",
                    max_wait=15,
                    log_func=print,
                    allow_chrome_fallback=chrome,
                    prefer_chrome=args.backend == "chrome",
                )
                assert page and marker in page, "A subsequent lookup failed after the challenge"
    finally:
        stopped.set()
        observer.join(timeout=5)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
    assert not violations, sorted(violations)
    _, alive = psutil.wait_procs(list(tracked), timeout=5)
    assert not alive, "Browser descendants survived cleanup"
    expected = ["embedded", "chrome"] if args.chrome_fallback else [args.backend] * (3 if args.failure_first else 1)
    assert attempts == expected, attempts
    if not page or marker not in page:
        raise AssertionError(f"{display_name} {args.backend} did not return the local fixture")
    if args.search_routes:
        from lxml.html import fromstring

        assert fromstring(page).xpath('//ul[@id="book-results"]//li/text()') == [marker]
        assert any(path.startswith("/json/") for path in _LocalPageHandler.paths)
        assert any(path.startswith("/search?") for path in _LocalPageHandler.paths)
        print("PASS: JSON error recovered through rendered HTML in one browser worker")
    if args.chrome_fallback:
        print(f"PASS: {display_name} used optional Chrome after simulated embedded failure and cleaned up")
    elif chrome:
        print(f"PASS: {display_name} rendered JavaScript with Chrome only and cleaned up")
    else:
        print(f"PASS: {display_name} rendered JavaScript without dialogs, external Chrome, or surviving workers")
    if check_sockets:
        print("PASS: no browser UDP sockets or non-loopback TCP listeners observed")


if __name__ == "__main__":
    main()
