#!/bin/bash
# Run this in Terminal after granting Terminal Full Disk Access
# (System Settings -> Privacy & Security -> Full Disk Access).
# Unlike export_folders.sh, this needs Full Disk Access, not the
# Automation permission -- it's a plain SQLite join, no AppleScript.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== automations ==="
python3 -m shortcuts_manager.cli automations

echo
echo "Done. Output is in $(cd "$(dirname "$0")/../.." && pwd)/ShortcutsExtracted"
