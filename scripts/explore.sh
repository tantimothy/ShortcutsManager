#!/bin/bash
# Diagnostic: map the real Shortcuts storage locations now that Terminal
# has Full Disk Access, since the Group Containers' Temporary/*.sqlite
# files turned out to be empty scratch databases.
set -uo pipefail

OUT="$(cd "$(dirname "$0")/../.." && pwd)/ShortcutsExtracted/explore"
mkdir -p "$OUT"

{
  echo "=== ~/Library/Shortcuts ==="
  find "$HOME/Library/Shortcuts" -maxdepth 6 2>&1
} > "$OUT/library_shortcuts_tree.txt"

{
  echo "=== group.com.apple.shortcuts (full tree, not just Temporary) ==="
  find "$HOME/Library/Group Containers/group.com.apple.shortcuts" -maxdepth 6 2>&1
} > "$OUT/group_apple_tree.txt"

{
  echo "=== group.is.workflow.shortcuts (full tree) ==="
  find "$HOME/Library/Group Containers/group.is.workflow.shortcuts" -maxdepth 6 2>&1
} > "$OUT/group_workflow_tree.txt"

{
  echo "=== file types for anything that looks like a DB or shortcut ==="
  find "$HOME/Library/Shortcuts" "$HOME/Library/Group Containers/group.com.apple.shortcuts" "$HOME/Library/Group Containers/group.is.workflow.shortcuts" \
    -type f \( -iname "*.sqlite*" -o -iname "*.shortcut" -o -iname "*.db" \) -exec file {} \; 2>&1
} > "$OUT/file_types.txt"

echo "Wrote exploration results to $OUT"
