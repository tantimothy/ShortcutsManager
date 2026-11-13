"""v3: apply ONLY the one-line rewiring fix (Set Variable 'JavaScript' ->
the correct, complete script instead of the broken one), with NO injected
diagnostic actions at all. Runs the shortcut's own original, native final
step (Show Alert, which already displays "Input: ... Output: ...") so the
only bindings in play are ones the app itself authored, not anything we
added -- ruling out whether externally-injected Show Result actions bind
reliably in this file.

Run:
    python3 examples/fix_remove_diacritics_v3.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut

NAME = "Remove Diacritics"
EXTRACTED = Path(f"<PROJECTS_DIR>/ShortcutsExtracted/unsigned/{NAME}.shortcut")
EDITED_UNSIGNED = EXTRACTED.with_suffix(".fixed-v3.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (fixed v3).shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

correct_uuid = "173C7831-9BCA-43E5-B289-92909919D82E"
set_js_action = actions[18]
assert set_js_action["WFWorkflowActionParameters"].get("WFVariableName") == "JavaScript"
set_js_action["WFWorkflowActionParameters"]["WFInput"] = {
    "Value": {"OutputName": "Text", "OutputUUID": correct_uuid, "Type": "ActionOutput"},
    "WFSerializationType": "WFTextTokenAttachment",
}

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed fixed shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it directly, type in text like "
    "'Café Façade' when asked, and let it run all the way through to its "
    "own final alert. Report exactly what that alert shows."
)
subprocess.run(["open", str(SIGNED)], check=True)
