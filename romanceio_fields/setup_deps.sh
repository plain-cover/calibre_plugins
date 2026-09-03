#!/bin/bash
# Install vendored dependencies into the plugin folder
# These are needed for SeleniumBase to work inside Calibre's embedded Python

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing dependencies for romanceio_fields plugin..."

# Build platform-neutral dependency trees for each Python runtime used by
# supported Calibre releases. The plugin picks one branch before importing
# Selenium; this avoids forcing Python 3.8 and current Python to share mutually
# incompatible SeleniumBase/Selenium versions.
# A Windows Store app-execution alias can appear in PATH as python3 even though
# Git Bash cannot execute it. Probe candidates before selecting one.
python_is_usable() {
    command -v "$1" &> /dev/null && "$1" -c 'import sys' &> /dev/null
}

if [ -n "${PYTHON:-}" ] && python_is_usable "$PYTHON"; then
    :
elif python_is_usable python3; then
    PYTHON=python3
elif python_is_usable python; then
    PYTHON=python
elif python_is_usable "$SCRIPT_DIR/../.romanceio/Scripts/python.exe"; then
    PYTHON="$SCRIPT_DIR/../.romanceio/Scripts/python.exe"
elif python_is_usable "$SCRIPT_DIR/../.romanceio/bin/python"; then
    PYTHON="$SCRIPT_DIR/../.romanceio/bin/python"
else
    echo "ERROR: A usable Python interpreter is required to install plugin dependencies"
    exit 1
fi

VENDOR_DIR="$SCRIPT_DIR/browser_vendor"
rm -rf -- "$VENDOR_DIR"
mkdir -p "$VENDOR_DIR/shared" "$VENDOR_DIR/py38" "$VENDOR_DIR/py39" "$VENDOR_DIR/current"

install_pure_python_manifest() {
    local manifest="$1"
    local python_version="$2"
    local target="$3"
    PIP_USER=false "$PYTHON" -m pip install \
        --require-hashes \
        --no-deps \
        --only-binary=:all: \
        --platform any \
        --implementation py \
        --python-version "$python_version" \
        --target "$target" \
        --upgrade \
        -r "$manifest"
}

install_pure_python_manifest "$SCRIPT_DIR/requirements.txt" 3.8 "$VENDOR_DIR/shared"
install_pure_python_manifest "$SCRIPT_DIR/requirements-py38.txt" 3.8 "$VENDOR_DIR/py38"
install_pure_python_manifest "$SCRIPT_DIR/requirements-py39.txt" 3.9 "$VENDOR_DIR/py39"
install_pure_python_manifest "$SCRIPT_DIR/requirements-current.txt" 3.10 "$VENDOR_DIR/current"

# Plugin modules import six before the browser helper has selected a vendor
# branch, so keep this one shared module at the ZIP root as well.
cp "$VENDOR_DIR/shared/six.py" "$SCRIPT_DIR/six.py"
"$PYTHON" -c 'import hashlib, pathlib, sys; h = hashlib.sha256(); [(h.update(pathlib.Path(p).name.encode("utf-8") + b"\0"), h.update(pathlib.Path(p).read_bytes()), h.update(b"\0")) for p in sys.argv[1:]]; print(h.hexdigest())' \
    "$SCRIPT_DIR/requirements.txt" \
    "$SCRIPT_DIR/requirements-py38.txt" \
    "$SCRIPT_DIR/requirements-py39.txt" \
    "$SCRIPT_DIR/requirements-current.txt" \
    "$SCRIPT_DIR/setup_deps.sh" > "$SCRIPT_DIR/.dependencies-installed"

echo "✓ Dependencies installed to $SCRIPT_DIR"
