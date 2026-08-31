"""Launch installed plugin Chrome against a local page with no third-party I/O."""

import argparse
import importlib
import os
import shutil
import stat
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PLUGINS = {
    "romanceio": "Romance.io",
    "romanceio_fields": "Romance.io Fields",
}


class _LocalPageHandler(BaseHTTPRequestHandler):
    body = b""

    def do_GET(self):  # pylint: disable=invalid-name
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", choices=sorted(PLUGINS))
    args = parser.parse_args()

    from calibre.customize.ui import find_plugin

    display_name = PLUGINS[args.plugin]
    plugin = find_plugin(display_name)
    if plugin is None:
        raise AssertionError(f"{display_name} is not installed")

    smoke_parent = os.environ.get("RUNNER_TEMP") or os.environ.get("CALIBRE_CONFIG_DIRECTORY") or tempfile.gettempdir()
    os.environ["CALIBRE_SELENIUM_HOME"] = os.path.join(smoke_parent, "browser-smoke", args.plugin)

    source_driver = _find_runner_chromedriver()
    seeded_driver = _seed_production_driver(source_driver)
    print(f"Seeded matching runner ChromeDriver: {source_driver} -> {seeded_driver}")

    helper = importlib.import_module(f"calibre_plugins.{args.plugin}.common_romanceio_fetch_helper")
    marker = "calibre-installed-plugin-browser-smoke-pass"
    html = f"<html><body><h1>{marker}</h1><p>{'local fixture ' * 20}</p></body></html>"
    _LocalPageHandler.body = html.encode("utf-8")
    server = _QuietHTTPServer(("127.0.0.1", 0), _LocalPageHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        local_url = f"http://127.0.0.1:{server.server_port}/browser-smoke"
        page = helper.fetch_page(
            local_url,
            args.plugin,
            wait_for_element=marker,
            max_wait=15,
            log_func=print,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
    if not page or marker not in page:
        raise AssertionError(f"{display_name} Chrome did not return the local fixture")
    print(f"PASS: {display_name} launched Chrome, read a local page, and shut down")


if __name__ == "__main__":
    main()
