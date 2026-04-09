#!/bin/bash

# Ensure dependencies are installed (idempotent - only installs if missing)
if [ ! -d "seleniumbase" ]; then
    echo "Dependencies not found, installing..."
    bash setup_deps.sh
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install dependencies"
        exit 1
    fi
    echo "Dependencies installed successfully"
else
    echo "Dependencies already present in seleniumbase/"
fi

# Use python3 if available (Linux/macOS), otherwise try python, then fall back to venv
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
elif [ -f ../.romanceio/Scripts/python.exe ]; then
    PYTHON=../.romanceio/Scripts/python.exe
elif [ -f ../.romanceio/bin/python ]; then
    PYTHON=../.romanceio/bin/python
else
    echo "Error: Python not found"
    exit 1
fi

$PYTHON build.py
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
