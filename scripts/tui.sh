#!/bin/bash
# Interactive menu over every shortcuts_manager.cli subcommand.
#
# Not a reimplementation -- every choice just runs the same
# `python3 -m shortcuts_manager.cli <command> ...` this project's other
# scripts/ wrappers run directly, so behavior (including error messages
# and exit codes) is identical to running the command yourself. This
# exists purely so you don't have to remember command names/flags, and so
# --name can be picked from an actual list instead of retyped by hand.
#
# Run:
#   scripts/tui.sh
#
# Full Disk Access is needed for most of this (see
# docs/full-disk-access.md); `folders` needs the separate Automation
# permission instead.
#
# No `set -u`: under it, macOS's stock bash (3.2 -- this ships with the
# OS and isn't updated) treats expanding an empty array (e.g.
# "${OUT_ARGS[@]}" when --out was left blank) as an unbound-variable
# error -- fixed in bash 4.4+, but that's what this script needs to run
# under here.
set -o pipefail

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This is macOS-only (Shortcuts.app, Full Disk Access, the" >&2
  echo "Automation permission, and /usr/bin/shortcuts all only exist" >&2
  echo "there) -- nothing to run on $(uname -s)." >&2
  exit 1
fi

cd "$(dirname "$0")/.."

CLI=(python3 -m shortcuts_manager.cli)

# Reads into $REPLY, trimmed. Returns 1 on EOF (Ctrl-D) so callers can
# treat that the same as "quit" instead of looping forever or erroring.
prompt() {
  local label="$1"
  read -r -p "$label: " REPLY || return 1
  REPLY="$(echo "$REPLY" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  return 0
}

# Appends --out <dir> to the OUT_ARGS array, left empty (cli.py's own
# default applies) if the prompt is left blank.
prompt_out() {
  OUT_ARGS=()
  prompt "Output directory (blank = default ../ShortcutsExtracted)" || return 1
  [ -n "$REPLY" ] && OUT_ARGS=(--out "$REPLY")
  return 0
}

# Sets NAME. Leaving it blank lists every shortcut first, then re-prompts.
prompt_name() {
  prompt "Shortcut name (blank to list shortcuts first)" || return 1
  if [ -z "$REPLY" ]; then
    "${CLI[@]}" list-shortcuts
    echo
    prompt "Shortcut name" || return 1
  fi
  NAME="$REPLY"
  return 0
}

# Runs one subcommand ("${CLI[@]} $*"), echoing the command line first and
# the exit code after, then pauses for Enter before returning to the menu.
run_cli() {
  echo
  echo "\$ ${CLI[*]} $*"
  echo
  "${CLI[@]}" "$@"
  local code=$?
  echo
  echo "(exit $code)"
  read -r -p $'\nPress Enter to return to the menu...' _ || true
}

print_menu() {
  echo
  echo "shortcuts_manager -- what do you want to do?"
  echo
  echo "  1) Inspect schema (tables/columns/row counts)"
  echo "  2) Dump every table's raw rows to JSON"
  echo "  3) List every shortcut by name"
  echo "  4) Extract one shortcut as an editable unsigned plist"
  echo "  5) Map a shortcut and everything it calls"
  echo "  6) Extract everything: plists, signed binaries, pseudocode, call graph"
  echo "  7) Export folder hierarchy"
  echo "  8) Export Personal Automations"
  echo "  q) Quit"
}

echo "shortcuts_manager interactive menu. Full Disk Access is needed for"
echo "most of this (see docs/full-disk-access.md); 'folders' needs the"
echo "separate Automation permission instead."

while true; do
  print_menu
  if ! prompt $'\nChoice [q]'; then
    echo
    break
  fi
  choice="${REPLY:-q}"

  case "$choice" in
    q|quit|exit) break ;;
    1) prompt_out && run_cli inspect "${OUT_ARGS[@]}" ;;
    2) prompt_out && run_cli dump-raw "${OUT_ARGS[@]}" ;;
    3) run_cli list-shortcuts ;;
    4) prompt_name && prompt_out && run_cli extract-one --name "$NAME" "${OUT_ARGS[@]}" ;;
    5) prompt_name && prompt_out && run_cli map-calls --name "$NAME" "${OUT_ARGS[@]}" ;;
    6) prompt_out && run_cli extract-all "${OUT_ARGS[@]}" ;;
    7) prompt_out && run_cli folders "${OUT_ARGS[@]}" ;;
    8) prompt_out && run_cli automations "${OUT_ARGS[@]}" ;;
    *) echo "Not a valid choice: $choice" ;;
  esac
done
