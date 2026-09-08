"""Verify that Calibre loads both plugins from their installed release ZIPs."""

import importlib
import os
import json
import tempfile
from pathlib import Path
import zipfile
from typing import Any

PLUGINS = (
    ("Romance.io", "romanceio", (1, 4, 0), (5, 0, 0), ("parse_html", "parse_json")),
    ("Romance.io Fields", "romanceio_fields", (1, 4, 0), (5, 0, 0), ("parse_html", "parse_json")),
)


def _origin(module):
    module_file = getattr(module, "__file__", None)
    if module_file == "<calibre Plugin Loader>":
        # Calibre 5.0 gives every plugin module the same placeholder filename.
        # Its actual loader records the owning ZIP by plugin import name.
        parts = module.__name__.split(".")
        loader = getattr(module, "__loader__", None)
        loaded_plugins = getattr(loader, "loaded_plugins", {})
        entry = loaded_plugins.get(parts[1]) if len(parts) > 1 and parts[0] == "calibre_plugins" else None
        module_file = entry[0] if isinstance(entry, (tuple, list)) and entry else None
    return os.path.normcase(os.path.abspath(module_file)) if module_file else ""


def _assert_installed_origin(module, plugin_path):
    module_path = _origin(module)
    expected_path = os.path.normcase(os.path.abspath(plugin_path))
    assert module_path == expected_path or module_path.startswith(
        expected_path + os.sep
    ), f"{module.__name__} did not load from its installed ZIP: {module_path}"


def _verify_existing_detail_setting(import_name):
    from types import SimpleNamespace
    from unittest.mock import patch

    package = "calibre_plugins." + import_name
    orchestrator = importlib.import_module(package + ".common_romanceio_search_orchestrator")
    cfg = importlib.import_module(package + ".config")
    for preferred in (False, True):
        calls = []

        def html(_book, _log, backend=None):
            calls.append(("browser", backend))
            if backend == "chrome":
                raise orchestrator.BrowserFetchError("Simulated Chrome failure")
            return orchestrator._BookNotFound()

        def http(_book, _log, **_kwargs):
            calls.append(("http", None))
            return None

        if import_name == "romanceio_fields":
            jobs = importlib.import_module(package + ".jobs")
            with patch.object(jobs, "_fetch_html", html), patch.object(jobs, "_fetch_html_lightweight", http):
                jobs.get_romanceio_fields_for_book("5484ecd47a5936fb0405756c", [], 50, prefer_html=preferred)
        else:
            worker_type = importlib.import_module(package + ".worker").Worker
            worker = worker_type.__new__(worker_type)
            worker.url = "https://www.romance.io/books/5484ecd47a5936fb0405756c"
            worker.abort = None
            worker.log = SimpleNamespace(info=lambda *_args: None, error=lambda *_args: None)
            worker._fetch_html = html
            worker._fetch_html_lightweight = http
            with patch.object(cfg, "plugin_prefs", {cfg.STORE_NAME: {cfg.KEY_PREFER_HTML: preferred}}):
                worker.get_details()
        assert calls == (
            [("browser", "chrome"), ("http", None), ("browser", "embedded")]
            if preferred
            else [("http", None), ("browser", None)]
        ), calls
    print(f"PASS: {import_name} preserves the existing website-tags setting and Chrome-first detail order")


def _verify_chrome_worker_isolation(installed_plugin_paths):
    import psutil
    from calibre.utils.ipc.simple_worker import fork_job

    owner = psutil.Process()
    for import_name, plugin_path in installed_plugin_paths.items():
        module_name = f"calibre_plugins.{import_name}.common_romanceio_fetch_helper"
        helper = importlib.import_module(module_name)
        source = fork_job(module_name, "resolve_browser_vendor_source", args=(import_name,), no_output=True)["result"]
        assert isinstance(source, str), f"Browser vendor source is not a path: {source!r}"
        assert os.path.normcase(os.path.abspath(source)) == os.path.normcase(plugin_path), source
        previous_home = os.environ.get("CALIBRE_SELENIUM_HOME")
        try:
            with tempfile.TemporaryDirectory(prefix="chrome-worker-check-") as transport:
                # A file cannot be used as the cache directory: fail before any
                # network or browser access, after exercising both worker hops.
                blocked = Path(transport) / "blocked-cache"
                blocked.write_text("", encoding="utf-8")
                os.environ["CALIBRE_SELENIUM_HOME"] = str(blocked)
                request = {
                    "url": "https://example.invalid",
                    "plugin_name": import_name,
                    "backend": "chrome",
                    "max_wait": 1,
                    "worker_timeout": 20,
                    "transport_dir": transport,
                    "owner_pid": owner.pid,
                    "owner_created": owner.create_time(),
                }
                result = fork_job(
                    module_name, "_supervise_browser_worker", args=(request,), timeout=40, no_output=True
                )["result"]
                assert isinstance(result, dict), result
                output = "\n".join(
                    json.loads(line)
                    for line in (Path(transport) / "progress.jsonl").read_text(encoding="utf-8").splitlines()
                )
                assert result.get("page", "missing") is None, result
                reason = helper.browser_automation_unavailable_reason()
                assert (reason or "Top-level error in fetch_page") in output, output
                assert "Starting Chrome" not in output, output
                assert "Starting Calibre embedded web engine" not in output, output
                assert "Browser worker failed" not in output, output
                if reason:
                    print(f"PASS: unsupported Chrome platform failed safely: {reason}")
        finally:
            if previous_home is None:
                os.environ.pop("CALIBRE_SELENIUM_HOME", None)
            else:
                os.environ["CALIBRE_SELENIUM_HOME"] = previous_home
        print(f"PASS: {import_name} nested Chrome worker isolation and installed dependency origin")


def _verify_search_failure_reporting():
    from queue import Queue
    from threading import Event
    from unittest.mock import patch
    from calibre.customize.ui import find_plugin
    from calibre.utils.logging import ThreadSafeLog

    plugin = find_plugin("Romance.io")
    assert plugin is not None, "Romance.io is not installed"
    api = importlib.import_module("calibre_plugins.romanceio.common_romanceio_json_api")
    helper = importlib.import_module("calibre_plugins.romanceio.fetch_helper")
    orchestrator = importlib.import_module("calibre_plugins.romanceio.common_romanceio_search_orchestrator")

    for outcome in ("recursion", "blocked", "empty", "empty"):

        def search(*_args, **_kwargs):
            if outcome == "recursion":
                raise RecursionError("TEST: recursive search")
            if outcome == "blocked":
                raise api.JsonApiAccessDeniedError("TEST: 403")
            return []

        def browser(*_args, **_kwargs):
            if outcome != "blocked":
                raise AssertionError("Unexpected browser call")
            raise orchestrator.BrowserFetchError("TEST: challenge timeout")

        orchestrator._last_json_request_time.clear()
        results: Queue[Any] = Queue()
        with patch.object(api, "search_books_json", search), patch.object(helper, "fetch_page", browser):
            error = plugin.identify(ThreadSafeLog(), results, Event(), title="Absent", authors=["Test Author"])
        assert results.empty()
        if outcome == "empty":
            assert error is None, error
        else:
            assert error and "search failed" in error.lower(), error
    print("PASS: installed identify reports failures and subsequent confirmed-empty lookups recover")


def main():
    # Import only when executed under calibre-debug. Keeping this out of module
    # scope lets the normal-Python deterministic suite collect this helper.
    from calibre.customize.ui import find_plugin

    installed_plugin_paths = {}
    for display_name, import_name, expected_version, expected_minimum, plugin_modules in PLUGINS:
        plugin = find_plugin(display_name)
        assert plugin is not None, f"{display_name} is not installed"

        plugin_path = os.path.abspath(plugin.plugin_path)
        installed_plugin_paths[import_name] = plugin_path
        assert zipfile.is_zipfile(plugin_path), f"Installed plugin is not a ZIP: {plugin_path}"
        assert tuple(plugin.version) == expected_version, (display_name, plugin.version)
        assert tuple(plugin.minimum_calibre_version) == expected_minimum, (
            display_name,
            plugin.minimum_calibre_version,
        )

        module = importlib.import_module(f"calibre_plugins.{import_name}")
        _assert_installed_origin(module, plugin_path)

        # Import the shared production modules through each installed plugin's
        # namespace. This catches path separators, zipimport, and Calibre plugin
        # loader differences without contacting Romance.io.
        for child_module in plugin_modules + (
            "common_romanceio_fetch_helper",
            "common_romanceio_json_api",
            "common_romanceio_webengine",
            "common_romanceio_session",
            "common_romanceio_transport",
            "common_romanceio_search_orchestrator",
        ):
            imported = importlib.import_module(f"calibre_plugins.{import_name}.{child_module}")
            _assert_installed_origin(imported, plugin_path)
            if child_module == "common_romanceio_fetch_helper":
                browser_source = os.path.normcase(os.path.abspath(imported.resolve_browser_vendor_source(import_name)))
                assert browser_source == os.path.normcase(plugin_path), browser_source

        _verify_existing_detail_setting(import_name)
        print(f"PASS: {display_name} v{'.'.join(map(str, expected_version))}: {plugin_path}")

    # Verify installed module resolution in Calibre's IPC worker as well as the
    # host. Actual rendering and cleanup are covered by the local browser tests.
    from calibre.utils.ipc.simple_worker import fork_job

    for import_name in installed_plugin_paths:
        result = fork_job(
            f"calibre_plugins.{import_name}.common_romanceio_webengine",
            "page_ready",
            args=(
                "<html><body><pre>" + '{"success":true,"books":[]}' + "</pre>" + " " * 100 + "</body></html>",
                "",
                {"url": "https://www.romance.io/json/search_books"},
            ),
            no_output=True,
        )["result"]
        assert result is True, f"Nested worker did not run installed WebEngine code: {import_name}"
    print("PASS: both nested Calibre workers executed the installed embedded-engine module")
    _verify_search_failure_reporting()
    _verify_chrome_worker_isolation(installed_plugin_paths)


if __name__ == "__main__":
    main()
