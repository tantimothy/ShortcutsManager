#!/bin/bash
# Run this in Terminal. Needs the Automation permission for this process to
# control Shortcuts.app (a one-time system prompt) -- NOT Full Disk Access,
# unlike extract.sh/explore.sh/map_calls.sh. If this hangs rather than
# finishing quickly, check for that permission prompt and approve it, then
# run this again.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== folders ==="
python3 -m shortcuts_manager.cli folders

echo
echo "Done. Output is in $(cd "$(dirname "$0")/../.." && pwd)/ShortcutsExtracted"
