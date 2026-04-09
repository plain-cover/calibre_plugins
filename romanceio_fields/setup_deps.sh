#!/bin/bash
# Install vendored dependencies into the plugin folder
# These are needed for SeleniumBase to work inside Calibre's embedded Python

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing dependencies for romanceio_fields plugin..."

# Install from local requirements.txt (runtime dependencies only)
# --no-deps prevents pulling in test frameworks from seleniumbase
# Set PIP_USER=false to prevent conflict with --target flag
PIP_USER=false pip install --no-deps -r "$SCRIPT_DIR/requirements.txt" --target "$SCRIPT_DIR" --upgrade

echo "✓ Dependencies installed to $SCRIPT_DIR"
