"""Deterministic coverage for conservative Linux/Flatpak browser discovery."""

import os
import types
from typing import List

import pytest

from common import run_installed_browser_smoke

from common.common_romanceio_fetch_helper import (
    _browser_binary_is_runnable,
    _build_chrome_args,
    _fetch_page_in_process,
    _find_flatpak_chrome,
    browser_automation_unavailable_reason,
    configure_browser_sandbox,
    configure_legacy_uc_subprocess,
)


def test_flatpak_chrome_searches_user_and_system_installs_and_probes_binary(monkeypatch):
    """Only directly executable Chrome binaries are returned."""
    patterns = []
    expected = "/var/lib/flatpak/app/com.google.Chrome/x86_64/stable/active/files/extra/google-chrome"

    monkeypatch.setattr("common.common_romanceio_fetch_helper.platform.system", lambda: "Linux")
    monkeypatch.setattr("common.common_romanceio_fetch_helper.os.path.expanduser", lambda _path: "/home/reader")

    def fake_glob(pattern):
        patterns.append(pattern)
        normalized = pattern.replace("\\", "/")
        return [expected] if normalized.startswith("/var/lib/flatpak/app/com.google.Chrome/") else []

    monkeypatch.setattr("common.common_romanceio_fetch_helper.glob.glob", fake_glob)
    monkeypatch.setattr(
        "common.common_romanceio_fetch_helper.os.access", lambda path, mode: path == expected and mode == os.X_OK
    )
    probes = []

    def record_probe(path):
        probes.append(path)
        return True

    monkeypatch.setattr(
        "common.common_romanceio_fetch_helper._browser_binary_is_runnable",
        record_probe,
    )

    assert _find_flatpak_chrome() == expected
    assert probes == [expected]
    normalized_patterns = [pattern.replace("\\", "/") for pattern in patterns]
    assert any(pattern.startswith("/home/reader/.local/share/flatpak/app/") for pattern in normalized_patterns)
    assert any(pattern.startswith("/var/lib/flatpak/app/") for pattern in normalized_patterns)


def test_flatpak_chrome_rejects_binary_that_cannot_run_in_current_environment(monkeypatch):
    expected = "/var/lib/flatpak/app/com.google.Chrome/x86_64/stable/active/files/extra/google-chrome"
    monkeypatch.setattr("common.common_romanceio_fetch_helper.platform.system", lambda: "Linux")
    monkeypatch.setattr("common.common_romanceio_fetch_helper.glob.glob", lambda _pattern: [expected])
    monkeypatch.setattr("common.common_romanceio_fetch_helper.os.access", lambda _path, _mode: True)
    monkeypatch.setattr("common.common_romanceio_fetch_helper._browser_binary_is_runnable", lambda _path: False)

    assert _find_flatpak_chrome() is None


def test_flatpak_chromium_app_launcher_is_never_treated_as_binary(monkeypatch):
    patterns = []
    monkeypatch.setattr("common.common_romanceio_fetch_helper.platform.system", lambda: "Linux")

    def record_pattern(pattern):
        patterns.append(pattern.replace("\\", "/"))
        return []

    monkeypatch.setattr(
        "common.common_romanceio_fetch_helper.glob.glob",
        record_pattern,
    )

    assert _find_flatpak_chrome() is None
    assert not any("org.chromium.Chromium" in pattern for pattern in patterns)


def test_flatpak_chrome_detection_is_linux_only(monkeypatch):
    monkeypatch.setattr("common.common_romanceio_fetch_helper.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "common.common_romanceio_fetch_helper.glob.glob",
        lambda _pattern: (_ for _ in ()).throw(AssertionError("glob should not run outside Linux")),
    )
    assert _find_flatpak_chrome() is None


def test_linux_arm_browser_automation_is_rejected_before_setup(monkeypatch):
    monkeypatch.setattr("common.common_romanceio_fetch_helper.platform.system", lambda: "Linux")
    monkeypatch.setattr("common.common_romanceio_fetch_helper.platform.machine", lambda: "aarch64")
    monkeypatch.setattr(
        "common.common_romanceio_fetch_helper.tempfile.mkdtemp",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("driver setup must not start on Linux ARM")),
    )
    messages: List[str] = []

    assert _fetch_page_in_process("https://example.invalid", "romanceio", log_func=messages.append) is None
    assert any("unavailable on Linux ARM (aarch64)" in message for message in messages)
    assert any("lightweight HTTP metadata remain available" in message for message in messages)


def test_browser_automation_platform_support_is_explicit():
    assert browser_automation_unavailable_reason("Linux", "arm64") is not None
    assert browser_automation_unavailable_reason("Linux", "armv8l") is not None
    assert browser_automation_unavailable_reason("Linux", "x86_64") is None
    assert browser_automation_unavailable_reason("Darwin", "arm64") is None
    assert browser_automation_unavailable_reason("Windows", "AMD64") is None


@pytest.mark.parametrize(
    "version_output",
    (
        "Google Chrome 140.0",
        "Google Chrome for Testing 140.0",
        "Google Chrome Beta 140.0",
        "Chromium 140.0",
    ),
)
def test_browser_binary_probe_requires_successful_chrome_version(monkeypatch, version_output):
    class Completed:
        returncode = 0
        stdout = version_output

    calls = []

    def successful_probe(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(
        "common.common_romanceio_fetch_helper.subprocess.run",
        successful_probe,
    )

    assert _browser_binary_is_runnable("/flatpak/google-chrome") is True
    assert calls[0][0][0] == ["/flatpak/google-chrome", "--version"]


def test_browser_binary_probe_rejects_launcher_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("launcher needs another Flatpak runtime")

    monkeypatch.setattr("common.common_romanceio_fetch_helper.subprocess.run", fail)
    assert _browser_binary_is_runnable("/flatpak/chromium-wrapper") is False


def test_no_sandbox_is_limited_to_flatpak():
    regular_args = _build_chrome_args("/tmp/profile", inside_flatpak=False, in_ci=False)
    flatpak_args = _build_chrome_args("/tmp/profile", inside_flatpak=True, in_ci=False)

    assert "--no-sandbox" not in regular_args
    assert "--no-sandbox" in flatpak_args
    assert "--window-position=-32000,-32000" in flatpak_args


def test_ci_window_argument_does_not_change_flatpak_sandboxing():
    args = _build_chrome_args("/tmp/profile", inside_flatpak=True, in_ci=True)
    assert "--no-sandbox" in args
    assert "--start-maximized" in args
    assert not any(arg.startswith("--window-position=") for arg in args)


@pytest.mark.parametrize("inside_flatpak", (False, True))
@pytest.mark.parametrize("version_info", ((3, 8), (3, 9), (3, 14)))
def test_final_chrome_command_enforces_sandbox_and_preserves_legacy_stdio(inside_flatpak, version_info):
    calls = []
    subprocess_module = types.SimpleNamespace(PIPE=-1, DEVNULL=-3, Popen=lambda *a, **kw: calls.append((a, kw)))
    undetected = types.SimpleNamespace(subprocess=subprocess_module)
    configure_legacy_uc_subprocess(undetected, version_info)
    configure_browser_sandbox(undetected, inside_flatpak)
    command = ["chrome", "--no-sandbox", "--disable-setuid-sandbox", "--no-sandbox=true", "--user-data-dir=profile"]
    undetected.subprocess.Popen(command, stdout=-1)
    actual_command = calls[0][0][0]
    assert actual_command == (command if inside_flatpak else ["chrome", "--user-data-dir=profile"])
    assert calls[0][1]["stdout"] == (-1 if version_info == (3, 14) else -3)
    assert len(command) == 5  # Do not mutate SeleniumBase's input.


def test_final_chrome_command_rejects_uninspectable_shell_launch():
    undetected = types.SimpleNamespace(
        subprocess=types.SimpleNamespace(Popen=lambda *_a, **_kw: pytest.fail("launched"))
    )
    configure_browser_sandbox(undetected, False)
    with pytest.raises(RuntimeError, match="explicit argument list"):
        undetected.subprocess.Popen("chrome --no-sandbox", shell=True)


def test_browser_smoke_managed_driver_does_not_require_runner_driver(monkeypatch):
    monkeypatch.setattr(
        run_installed_browser_smoke,
        "_find_runner_chromedriver",
        lambda: (_ for _ in ()).throw(AssertionError("runner driver must not be inspected")),
    )

    assert run_installed_browser_smoke._prepare_driver("managed") is None


def test_browser_smoke_runner_driver_is_seeded(monkeypatch):
    monkeypatch.setattr(run_installed_browser_smoke, "_find_runner_chromedriver", lambda: "/runner/chromedriver")
    monkeypatch.setattr(
        run_installed_browser_smoke,
        "_seed_production_driver",
        lambda source: f"/seeded/{source.rsplit('/', 1)[-1]}",
    )

    assert run_installed_browser_smoke._prepare_driver("runner") == "/seeded/chromedriver"


def test_browser_smoke_requires_detectable_flatpak_chrome(monkeypatch):
    class Helper:
        @staticmethod
        def _find_flatpak_chrome():
            return "/flatpak/com.google.Chrome/google-chrome"

    monkeypatch.setenv("FLATPAK_ID", "com.calibre_ebook.calibre")
    assert run_installed_browser_smoke._verify_flatpak_chrome(Helper) == "/flatpak/com.google.Chrome/google-chrome"


def test_browser_smoke_rejects_missing_flatpak_chrome(monkeypatch):
    class Helper:
        @staticmethod
        def _find_flatpak_chrome():
            return None

    monkeypatch.setenv("FLATPAK_ID", "com.calibre_ebook.calibre")
    with pytest.raises(AssertionError, match="directly runnable Flatpak Chrome"):
        run_installed_browser_smoke._verify_flatpak_chrome(Helper)
