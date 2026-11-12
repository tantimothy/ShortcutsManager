#!/bin/bash
# Run this in Terminal after granting Terminal Full Disk Access
# (System Settings -> Privacy & Security -> Full Disk Access).
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== inspect ==="
python3 -m shortcuts_manager.cli inspect

echo
echo "=== dump-raw ==="
python3 -m shortcuts_manager.cli dump-raw

echo
echo "Done. Output is in <PROJECTS_DIR>/ShortcutsExtracted"
