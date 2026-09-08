"""Exercise installed embedded-engine cleanup after caller death or a navigation timeout.

Run with calibre-debug -e common/run_installed_browser_lifecycle.py -- cancel
(or timeout). Uses a local HTTP server and an isolated Calibre configuration.
"""

import argparse
import importlib
import os
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    import psutil
    from calibre.utils.ipc.simple_worker import two_part_fork_job

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("cancel", "timeout"))
    args = parser.parse_args()
    # Keep browser session/cache files outside the normal plugin cache.
    if not os.environ.get("CALIBRE_SELENIUM_HOME"):
        base = os.environ.get("RUNNER_TEMP") or os.environ.get("CALIBRE_CONFIG_DIRECTORY") or tempfile.gettempdir()
        os.environ["CALIBRE_SELENIUM_HOME"] = os.path.join(base, "browser-smoke", "romanceio_fields")
    helper = importlib.import_module("calibre_plugins.romanceio_fields.common_romanceio_fetch_helper")
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # pylint: disable=invalid-name
            release.wait(60)
            self.close_connection = True

        def log_message(self, *_args):
            pass

    class Server(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            # Stopping the browser intentionally resets its outstanding local requests.
            pass

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    transport = tempfile.mkdtemp(prefix="browser_lifecycle_")
    owner = psutil.Process()
    request = {
        "url": f"http://127.0.0.1:{server.server_port}/stall",
        "plugin_name": "romanceio_fields",
        "max_wait": 60,
        "transport_dir": transport,
        "worker_timeout": 20,
        "owner_pid": owner.pid,
        "owner_created": owner.create_time(),
    }
    run_job = two_part_fork_job()
    outer = psutil.Process(run_job.worker.pid)
    tracked = set()
    results = []
    errors = []
    profiles = set()
    process_names = set()
    output = ""

    def run():
        try:
            if args.mode == "cancel":
                results.append(run_job(helper.__name__, "fetch_page", args=(request["url"], "romanceio_fields")))
            else:
                results.append(run_job(helper.__name__, "_supervise_browser_worker", args=(request,)))
        except Exception as error:  # pylint: disable=broad-except
            errors.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    cancelled = False
    started = time.monotonic()
    previous = ""
    try:
        while time.monotonic() - started < 45:
            try:
                tracked.update(outer.children(recursive=True))
            except psutil.NoSuchProcess:
                pass
            for process in list(tracked):
                try:
                    tracked.update(process.children(recursive=True))
                    process_names.add(process.name().lower())
                    for arg in process.cmdline():
                        if arg.startswith("--user-data-dir="):
                            profiles.add(arg.split("=", 1)[1])
                except psutil.NoSuchProcess:
                    pass
            log_path = Path(run_job.worker.log_path) if args.mode == "cancel" else Path(transport) / "progress.jsonl"
            if log_path.exists():
                output = log_path.read_text(encoding="utf-8", errors="replace")
                if output != previous:
                    print(output[len(previous) :], end="", flush=True)
                    previous = output
            if args.mode == "cancel" and "Navigating embedded web engine to" in output and not cancelled:
                print("TEST: Killing Calibre's outer job during navigation", flush=True)
                run_job.worker.kill()
                cancelled = True
            if not thread.is_alive() and all(not process.is_running() for process in tracked):
                break
            time.sleep(0.1)
        assert "Starting Calibre embedded web engine" in output, output
        assert "Navigating embedded web engine to" in output, output
        assert tracked, "No worker descendants observed"
        assert not any(
            "chromedriver" in name or name in ("chrome.exe", "chrome", "uc_driver.exe") for name in process_names
        ), process_names
        assert not thread.is_alive(), "Outer job did not finish"
        assert all(not process.is_running() for process in tracked), "Browser descendants survived"
        assert all(not os.path.exists(profile) for profile in profiles), "Browser profile survived cleanup"
        if args.mode == "cancel":
            assert cancelled and errors, (cancelled, errors)
        else:
            assert not errors, errors
            response = results[0]["result"]
            assert response["error_type"] == "BrowserFetchError", response
            assert "time limit" in response["error_message"], response
        print(
            f"PASS: {args.mode}: job stopped, browser descendants exited, and profiles removed ({time.monotonic()-started:.1f}s)"
        )
    finally:
        run_job.worker.kill()
        for process in tracked:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        release.set()
        server.shutdown()
        server.server_close()
        shutil.rmtree(transport, ignore_errors=True)


if __name__ == "__main__":
    main()
