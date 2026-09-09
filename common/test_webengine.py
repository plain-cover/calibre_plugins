"""Validate readiness without importing Qt or opening a browser."""

from typing import Any, Dict, List

import pytest
from common.common_romanceio_webengine import page_ready


@pytest.mark.parametrize("existing_flags", ("", "--disable-logging"))
def test_embedded_worker_disables_gpu_before_importing_qt(monkeypatch, existing_flags):
    import builtins
    import os
    from common.common_romanceio_webengine import fetch_page

    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", existing_flags)
    original_import = builtins.__import__

    class QtImportReached(Exception):
        pass

    def checked_import(name, *args, **kwargs):
        if name == "calibre.gui2":
            flags = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split()
            assert "--disable-gpu" in flags
            assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in flags
            assert "--disable-quic" in flags
            assert set(existing_flags.split()).issubset(flags)
            assert "--no-sandbox" not in flags
            raise QtImportReached()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    with pytest.raises(QtImportReached):
        fetch_page({"url": "http://127.0.0.1/fixture"}, lambda _message: None)


def document(body):
    return "<html><head></head><body>" + body + "<!--" + " " * 100 + "--></body></html>"


def test_json_waits_for_actual_payload():
    request = {"url": "https://www.romance.io/json/search_books?search=test"}
    assert not page_ready(document("<pre>Checking your browser</pre>"), "Just a moment...", request)
    assert not page_ready(document('<pre>{"success":</pre>'), "", request)
    assert page_ready(document('<pre>{"success":true,"books":[]}</pre>'), "", request)
    assert not page_ready(document('<pre>{"success":false}</pre>'), "", request)


@pytest.mark.parametrize("marker,expected", [("book-stats", True), ("unrelated", False)])
def test_html_requires_expected_content(marker, expected):
    request = {"url": "https://www.romance.io/books/test", "wait_for_element": "book-stats"}
    assert page_ready(document(marker), "Book", request) is expected
    assert not page_ready(document(marker), "Just a moment...", request)


def test_not_found_completes_without_expected_element():
    request = {
        "url": "https://www.romance.io/books/test",
        "wait_for_element": "book-stats",
        "not_found_marker": "not found",
    }
    assert page_ready(document("NOT FOUND"), "Missing book", request)


def test_optional_chrome_fallback_order(monkeypatch):
    from common import common_romanceio_fetch_helper as helper

    calls = []
    logs: List[str] = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(request, log, abort):
        calls.append(request.get("backend", "embedded"))
        if calls[-1] == "embedded":
            raise helper.BrowserFetchError("Challenge could not be cleared")
        return "Chrome page"

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    assert helper.fetch_page("https://www.romance.io", "romanceio", log_func=logs.append) == "Chrome page"
    assert calls == ["embedded", "chrome"]
    assert "Embedded browser failed: Challenge could not be cleared" in logs


@pytest.mark.parametrize("outcome", ["disabled", "cancelled", "success", "chrome-fails"])
def test_chrome_does_not_launch_unnecessarily_or_repeat(monkeypatch, outcome):
    import threading
    from common import common_romanceio_fetch_helper as helper

    calls = []
    abort = threading.Event()
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(request, log, event):
        calls.append(request.get("backend", "embedded"))
        if outcome == "success":
            return "Valid empty results or not-found page"
        if outcome == "cancelled":
            abort.set()
        raise helper.BrowserFetchError("Failed")

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    if outcome == "success":
        helper.fetch_page("https://www.romance.io", "romanceio", abort=abort, allow_chrome_fallback=True)
    else:
        with pytest.raises(helper.BrowserFetchError):
            helper.fetch_page(
                "https://www.romance.io", "romanceio", abort=abort, allow_chrome_fallback=outcome != "disabled"
            )
    assert calls == (["embedded", "chrome"] if outcome == "chrome-fails" else ["embedded"])


def test_existing_chrome_first_preference(monkeypatch):
    from common import common_romanceio_fetch_helper as helper

    calls = []
    monkeypatch.setattr(helper, "_is_installed_plugin_module", lambda _name: True)

    def fetch(request, log, abort):
        calls.append(request.get("backend", "embedded"))
        if calls[-1] == "chrome":
            raise helper.BrowserFetchError("Chrome unavailable")
        return "Rendered details"

    monkeypatch.setattr(helper, "_fetch_page_via_calibre_worker", fetch)
    assert helper.fetch_page("https://www.romance.io", "romanceio", prefer_chrome=True) == "Rendered details"
    assert calls == ["chrome", "embedded"]


@pytest.mark.parametrize("backend", ("embedded", "chrome"))
def test_smoke_accepts_only_expected_challenge_failure(backend):
    from common.run_installed_browser_smoke import _verify_challenge_failure

    if backend == "embedded":
        message = "Embedded web engine timed out waiting for validated content or Cloudflare clearance"
        logs = []
    else:
        message = "Browser did not return a page; see the preceding browser log"
        logs = ["Chrome error: BrowserFetchError: Chrome did not return validated content within its navigation budget"]
    _verify_challenge_failure(RuntimeError(message), backend, logs)


@pytest.mark.parametrize("backend", ("embedded", "chrome"))
@pytest.mark.parametrize("message", ("Browser worker failed", "Embedded web engine renderer exited unexpectedly"))
def test_smoke_rejects_native_crash_as_challenge_failure(backend, message):
    from common.run_installed_browser_smoke import _verify_challenge_failure

    with pytest.raises(AssertionError, match="Challenge lookup failed unexpectedly"):
        _verify_challenge_failure(RuntimeError(message), backend, [])


def test_smoke_rejects_chrome_setup_failure():
    from common.run_installed_browser_smoke import _verify_challenge_failure

    with pytest.raises(AssertionError, match="Challenge lookup failed unexpectedly"):
        _verify_challenge_failure(
            RuntimeError("Browser did not return a page; see the preceding browser log"),
            "chrome",
            ["Chrome error: SessionNotCreatedException: Driver failed to start"],
        )


@pytest.mark.parametrize("optimize", (1, 2))
def test_smoke_rejects_worker_crashes_with_optimized_python(optimize):
    import inspect
    from common.run_installed_browser_smoke import _verify_challenge_failure

    namespace: Dict[str, Any] = {}
    code = compile(inspect.getsource(_verify_challenge_failure), "smoke_check", "exec", optimize=optimize)
    exec(code, namespace)  # pylint: disable=exec-used
    with pytest.raises(AssertionError, match="Challenge lookup failed unexpectedly"):
        namespace["_verify_challenge_failure"](RuntimeError("Browser worker failed"), "embedded", [])


@pytest.mark.parametrize(
    "filename",
    (
        "run_installed_browser_smoke.py",
        "run_installed_browser_lifecycle.py",
        "run_installed_live_smoke.py",
        "test_installed_plugins.py",
        "test_release_zip_imports.py",
    ),
)
def test_frozen_calibre_checks_are_not_stripped(filename):
    import ast
    from pathlib import Path

    tree = ast.parse(Path(__file__).with_name(filename).read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.Assert) for node in ast.walk(tree)
    ), f"{filename}: Calibre strips assert statements; use an explicit exception for smoke checks"
