#!/bin/bash
# Run this in Terminal after granting Terminal Full Disk Access
# (System Settings -> Privacy & Security -> Full Disk Access).
#
# Runs the full extraction pipeline in one go: schema/raw forensic dump,
# every shortcut (unsigned plist, signed binary, pseudocode, call graph),
# Personal Automations, and folder hierarchy.
#
# `folders` additionally needs the Automation permission for this process
# to control Shortcuts.app (a one-time system prompt, separate from Full
# Disk Access) -- if it hangs instead of finishing, check for that prompt,
# approve it, and re-run just that step:
#   python3 -m shortcuts_manager.cli folders
#
# Every step's output (including a failing step's full traceback) is both
# shown here and saved to extract_everything.log in this repo's root --
# gitignored, not meant to be committed -- so it can be read back without
# retyping or screenshotting a truncated terminal.
#
# No `set -e`: one step failing (like a traceback) must not silently skip
# the rest, which is exactly what happened before this was added.
set -uo pipefail

cd "$(dirname "$0")/.."

LOG="$(pwd)/extract_everything.log"
exec > >(tee "$LOG") 2>&1

echo "=== inspect ==="
python3 -m shortcuts_manager.cli inspect || echo "inspect step failed (see above)."

echo
echo "=== dump-raw ==="
python3 -m shortcuts_manager.cli dump-raw || echo "dump-raw step failed (see above)."

echo
echo "=== extract-all ==="
python3 -m shortcuts_manager.cli extract-all || echo "extract-all step failed (see above)."

echo
echo "=== automations ==="
python3 -m shortcuts_manager.cli automations || echo "automations step failed (see above)."

echo
echo "=== folders ==="
python3 -m shortcuts_manager.cli folders || echo "folders step failed -- see above (likely needs the Automation permission approved); re-run 'python3 -m shortcuts_manager.cli folders' on its own once that's done."

echo
echo "Done. Output is in $(cd "$(dirname "$0")/../.." && pwd)/ShortcutsExtracted"
echo "Full log: $LOG"
