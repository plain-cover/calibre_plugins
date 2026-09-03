"""Verify that Calibre loads both plugins from their installed release ZIPs."""

import importlib
import os
import tempfile
import zipfile

PLUGINS = (
    ("Romance.io", "romanceio", (1, 4, 0), (5, 0, 0), ("parse_html", "parse_json")),
    ("Romance.io Fields", "romanceio_fields", (1, 4, 0), (5, 0, 0), ("parse_html", "parse_json")),
)


def _origin(module):
    return os.path.abspath(str(getattr(module, "__file__", "") or ""))


def main():
    # Import only when executed under calibre-debug. Keeping this out of module
    # scope lets the normal-Python deterministic suite collect this helper.
    from calibre.customize.ui import find_plugin

    for display_name, import_name, expected_version, expected_minimum, plugin_modules in PLUGINS:
        plugin = find_plugin(display_name)
        assert plugin is not None, f"{display_name} is not installed"

        plugin_path = os.path.abspath(plugin.plugin_path)
        assert zipfile.is_zipfile(plugin_path), f"Installed plugin is not a ZIP: {plugin_path}"
        assert tuple(plugin.version) == expected_version, (display_name, plugin.version)
        assert tuple(plugin.minimum_calibre_version) == expected_minimum, (
            display_name,
            plugin.minimum_calibre_version,
        )

        module = importlib.import_module(f"calibre_plugins.{import_name}")
        module_path = _origin(module)
        assert module_path.startswith(
            plugin_path
        ), f"{display_name} loaded from the checkout instead of its installed ZIP: {module_path}"

        # Import the shared production modules through each installed plugin's
        # namespace. This catches path separators, zipimport, and Calibre plugin
        # loader differences without contacting Romance.io.
        for child_module in plugin_modules + (
            "common_romanceio_fetch_helper",
            "common_romanceio_json_api",
            "common_romanceio_search_orchestrator",
        ):
            imported = importlib.import_module(f"calibre_plugins.{import_name}.{child_module}")
            imported_path = _origin(imported)
            assert imported_path.startswith(
                plugin_path
            ), f"{display_name}.{child_module} did not load from the installed ZIP: {imported_path}"

        print(f"PASS: {display_name} v{'.'.join(map(str, expected_version))}: {plugin_path}")

    # Romance.io Fields already runs inside a Calibre job worker. Confirm that
    # its public browser entry point can start the additional disposable worker
    # used to contain vendored import-table changes. A regular file is used as
    # CALIBRE_SELENIUM_HOME so setup stops deterministically before network or
    # Chrome access; the inner worker's captured log proves both process hops ran.
    from calibre.utils.ipc.simple_worker import fork_job

    helper = importlib.import_module("calibre_plugins.romanceio_fields.common_romanceio_fetch_helper")
    unavailable_reason = helper.browser_automation_unavailable_reason()

    previous_selenium_home = os.environ.get("CALIBRE_SELENIUM_HOME")
    worker_log_path = None
    try:
        with tempfile.NamedTemporaryFile() as blocked_directory:
            os.environ["CALIBRE_SELENIUM_HOME"] = blocked_directory.name
            worker_result = fork_job(
                "calibre_plugins.romanceio_fields.common_romanceio_fetch_helper",
                "fetch_page",
                args=("https://example.invalid", "romanceio_fields"),
                kwargs={"max_wait": 1},
                timeout=60,
            )
        worker_log_path = worker_result["stdout_stderr"]
        with open(worker_log_path, "rb") as worker_log:
            output = worker_log.read().decode("utf-8", "replace")
        assert worker_result["result"] is None
        if unavailable_reason:
            assert unavailable_reason in output, output
            print(f"PASS: unsupported browser platform failed safely: {unavailable_reason}")
        else:
            assert "Top-level error in fetch_page" in output, output
        assert "Browser worker failed" not in output, output
        print("PASS: nested Calibre browser worker isolation")
    finally:
        if previous_selenium_home is None:
            os.environ.pop("CALIBRE_SELENIUM_HOME", None)
        else:
            os.environ["CALIBRE_SELENIUM_HOME"] = previous_selenium_home
        if worker_log_path and os.path.exists(worker_log_path):
            try:
                os.remove(worker_log_path)
            except OSError:
                # Calibre's worker-kill thread can retain the log briefly on Windows.
                pass


if __name__ == "__main__":
    main()
