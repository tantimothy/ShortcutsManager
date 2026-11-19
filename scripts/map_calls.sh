#!/bin/bash
# Run this in Terminal (needs Full Disk Access, same as extract.sh).
# Usage: scripts/map_calls.sh "Post Article"
set -euo pipefail

cd "$(dirname "$0")/.."

NAME="${1:-Post Article}"

echo "=== map-calls: \"$NAME\" ==="
python3 -m shortcuts_manager.cli map-calls --name "$NAME"

echo
echo "Done. Output is in $(cd "$(dirname "$0")/../.." && pwd)/ShortcutsExtracted"
