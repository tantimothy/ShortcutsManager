"""Build a disposable, two-action dummy shortcut for safely testing the
extract -> edit -> sign -> re-import loop, without touching a real one.

Run: python3 examples/dummy_for_editing.py
Click "Add Shortcut" when Shortcuts.app opens, then:
    python3 -m shortcuts_manager.cli extract-one --name "ShortcutsManager Dummy"
edit its WFWorkflowActions, sign it, and reopen it to see the edit land.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import new_workflow, write_unsigned, sign
from shortcuts_manager.actions import text, show_result

NAME = "ShortcutsManager Dummy"
DIR = Path(__file__).resolve().parent
UNSIGNED = DIR / f"{NAME}.unsigned.shortcut"
SIGNED = DIR / f"{NAME}.shortcut"

workflow = new_workflow([
    text("Dummy value"),
    show_result("This is a disposable test shortcut -- safe to edit or delete."),
])
write_unsigned(workflow, UNSIGNED)
sign(UNSIGNED, SIGNED, mode="anyone")
UNSIGNED.unlink()
print(f"Signed shortcut written: {SIGNED}")

print("Opening in Shortcuts.app -- click 'Add Shortcut' there to import it.")
subprocess.run(["open", str(SIGNED)], check=True)
