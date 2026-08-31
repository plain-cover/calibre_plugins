#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use python3 if available (Linux/macOS), otherwise try python, then fall back to venv
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
elif [ -f "$SCRIPT_DIR/../.romanceio/Scripts/python.exe" ]; then
    PYTHON="$SCRIPT_DIR/../.romanceio/Scripts/python.exe"
elif [ -f "$SCRIPT_DIR/../.romanceio/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/../.romanceio/bin/python"
else
    echo "Error: Python not found"
    exit 1
fi

cd "$SCRIPT_DIR" || exit 1

dependency_fingerprint() {
    "$PYTHON" -c 'import hashlib, pathlib, sys; h = hashlib.sha256(); [(h.update(pathlib.Path(p).name.encode("utf-8") + b"\0"), h.update(pathlib.Path(p).read_bytes()), h.update(b"\0")) for p in sys.argv[1:]]; print(h.hexdigest())' \
        "$SCRIPT_DIR/requirements.txt" \
        "$SCRIPT_DIR/requirements-py38.txt" \
        "$SCRIPT_DIR/requirements-py39.txt" \
        "$SCRIPT_DIR/requirements-current.txt" \
        "$SCRIPT_DIR/setup_deps.sh"
}

# Ensure every dependency branch exists and was produced from the exact current
# manifests/setup logic. A content digest avoids stale builds after branch
# switches, timestamp preservation, or setup_deps.sh-only changes.
DEPS_STAMP="$SCRIPT_DIR/.dependencies-installed"
EXPECTED_DEPS_FINGERPRINT="$(dependency_fingerprint)"
NEEDS_DEPS=false
for required_path in \
    "browser_vendor/shared/seleniumbase" \
    "browser_vendor/shared/socks.py" \
    "browser_vendor/py38/selenium" \
    "browser_vendor/py39/selenium" \
    "browser_vendor/current/seleniumbase"; do
    if [ ! -e "$required_path" ]; then
        NEEDS_DEPS=true
    fi
done
if [ ! -f "$DEPS_STAMP" ] || [ "$(cat "$DEPS_STAMP" 2>/dev/null)" != "$EXPECTED_DEPS_FINGERPRINT" ]; then
    NEEDS_DEPS=true
fi

if [ "$NEEDS_DEPS" = true ]; then
    echo "Dependencies missing or dependency inputs changed, installing..."
    bash setup_deps.sh
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install dependencies"
        exit 1
    fi
    echo "Dependencies installed successfully"
else
    echo "Dependencies already match runtime manifests"
fi

"$PYTHON" build.py
if [ $? -ne 0 ]; then
    echo "Build script failed"
    exit 1
fi

# Determine the zip file that just got created
PLUGIN_ZIP=$(ls -t *.zip | head -n 1)

echo "Installing plugin \"$PLUGIN_ZIP\" into calibre..."
if [ -n "$CALIBRE_DIRECTORY" ]; then
    "$CALIBRE_DIRECTORY/calibre-customize" -a "$PLUGIN_ZIP"
else
    calibre-customize -a "$PLUGIN_ZIP"
fi

echo "Build completed successfully"
