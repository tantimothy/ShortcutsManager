"""Build a one-action shortcut, read the plist back to check it, sign it,
then open it in Shortcuts.app to prove the signed file is valid.

Run: python3 examples/hello_world.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import new_workflow, write_unsigned, sign, read_shortcut
from shortcuts_manager.actions import show_result

DIR = Path(__file__).resolve().parent
UNSIGNED = DIR / "Hello World.unsigned.shortcut"
SIGNED = DIR / "Hello World.shortcut"

workflow = new_workflow([show_result("Hello from ShortcutsManager!")])
write_unsigned(workflow, UNSIGNED)

built = read_shortcut(UNSIGNED)
action0 = built["WFWorkflowActions"][0]
print("Built action identifier:", action0["WFWorkflowActionIdentifier"])
print("Built action parameters:", action0["WFWorkflowActionParameters"])

sign(UNSIGNED, SIGNED, mode="anyone")
UNSIGNED.unlink()
print(f"Signed shortcut written: {SIGNED}")

print("Opening in Shortcuts.app -- click 'Add Shortcut' there to import it.")
subprocess.run(["open", str(SIGNED)], check=True)
