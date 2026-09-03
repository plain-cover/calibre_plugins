"""Keep both plugin builds on the same runtime-specific browser stacks."""

import zipfile
from pathlib import Path

from build_utils import add_folder_to_zip, create_zip_file

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = (
    "requirements.txt",
    "requirements-py38.txt",
    "requirements-py39.txt",
    "requirements-current.txt",
)
PYTHON_SELECTING_SCRIPTS = tuple(
    ROOT / plugin / script for plugin in ("romanceio", "romanceio_fields") for script in ("build.sh", "setup_deps.sh")
)


def _manifest(plugin, name):
    return (ROOT / plugin / name).read_text(encoding="utf-8")


def test_plugin_dependency_manifests_are_identical():
    for name in MANIFESTS:
        assert _manifest("romanceio", name) == _manifest("romanceio_fields", name), name


def test_seleniumbase_versions_are_split_by_supported_runtime():
    shared = _manifest("romanceio", "requirements.txt")
    current = _manifest("romanceio", "requirements-current.txt")
    assert "seleniumbase==4.44.20" in shared
    assert "seleniumbase==4.52.4" in current
    assert "PySocks==1.7.1" in shared
    assert "selenium==4.27.1" in _manifest("romanceio", "requirements-py38.txt")
    assert "selenium==4.47.0" in current


def test_every_dependency_is_hash_locked():
    for plugin in ("romanceio", "romanceio_fields"):
        for name in MANIFESTS:
            manifest = _manifest(plugin, name)
            requirements = [line for line in manifest.splitlines() if line and not line.startswith(("#", " ", "--"))]
            assert requirements, (plugin, name)
            assert manifest.count("--hash=sha256:") == len(requirements), (plugin, name)


def test_shell_scripts_probe_python_before_selecting_it():
    """Do not select an unusable Windows Store alias merely because it exists."""
    for script_path in PYTHON_SELECTING_SCRIPTS:
        script = script_path.read_text(encoding="utf-8")
        assert 'command -v "$1"' in script, script_path
        assert "\"$1\" -c 'import sys'" in script, script_path
        assert "elif python_is_usable python3" in script, script_path
        assert "elif python_is_usable python" in script, script_path
        assert '.romanceio/Scripts/python.exe"' in script, script_path
        assert '.romanceio/bin/python"' in script, script_path


def test_release_folder_packaging_excludes_nested_command_debris(tmp_path):
    vendor = tmp_path / "browser_vendor" / "current"
    package = vendor / "runtime_package"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    for directory in ("bin", "mcp_servers", "sbase"):
        debris = vendor / directory
        debris.mkdir()
        (debris / "launcher.exe").write_bytes(b"not portable")
    (vendor / "sockshandler.py").write_text("raise SystemExit\n", encoding="utf-8")

    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as plugin_zip:
        add_folder_to_zip(plugin_zip, str(tmp_path / "browser_vendor"))

    with zipfile.ZipFile(archive) as plugin_zip:
        names = plugin_zip.namelist()
    assert any(name.endswith("runtime_package/__init__.py") for name in names)
    assert not any("/bin/" in name or "/mcp_servers/" in name or "/sbase/" in name for name in names)
    assert not any(name.endswith("sockshandler.py") for name in names)


def test_release_zip_adds_legacy_certifi_resource_alias(tmp_path, monkeypatch):
    """Keep certifi usable through nested zipimport on Python 3.8 and 3.9."""
    monkeypatch.chdir(tmp_path)
    certificate = tmp_path / "browser_vendor" / "shared" / "certifi" / "cacert.pem"
    certificate.parent.mkdir(parents=True)
    certificate.write_bytes(b"test certificate bundle")

    create_zip_file("plugin.zip", "w", ["browser_vendor"])

    with zipfile.ZipFile("plugin.zip") as plugin_zip:
        assert plugin_zip.read("certifi/cacert.pem") == certificate.read_bytes()
        assert "certifi/__init__.py" not in plugin_zip.namelist()
