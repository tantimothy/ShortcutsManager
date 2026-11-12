"""Proves the edit loop: load the plist extract-one produced, change its
action parameters, sign it, and reopen it for re-import.

Run after:
    python3 -m shortcuts_manager.cli extract-one --name "ShortcutsManager Dummy"

    python3 examples/edit_dummy.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut

NAME = "ShortcutsManager Dummy"
EXTRACTED = Path(f"<PROJECTS_DIR>/ShortcutsExtracted/unsigned/{NAME}.shortcut")
EDITED_UNSIGNED = EXTRACTED.with_suffix(".edited.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (edited).shortcut"

workflow = read_shortcut(EXTRACTED)
workflow["WFWorkflowActions"][0]["WFWorkflowActionParameters"]["WFTextActionText"] = (
    "Edited by ShortcutsManager!"
)
workflow["WFWorkflowActions"][1]["WFWorkflowActionParameters"]["Text"] = (
    "If you can read this, the extract-edit-sign-import loop works."
)

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed edited shortcut written: {SIGNED}")

print("Opening in Shortcuts.app -- click 'Add Shortcut' there to import the edit.")
subprocess.run(["open", str(SIGNED)], check=True)
