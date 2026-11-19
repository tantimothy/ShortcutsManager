"""Fix for Remove Diacritics: "Set Variable 'JavaScript'" (action 18) is
wired to a broken, orphaned 92-char snippet (action 17 -- discards its own
computed result, then calls completion(result) with an undefined `result`,
which is the wrong calling convention for "Get Contents of Web Page"
anyway) instead of the complete, correct 9086-char removeDiacritics()
script sitting right next to it (action 16, which document.write()s its
result -- the right convention for this action) that nothing else uses.

Rewires action 18 to reference action 16's output instead. Truncated right
after "Get Contents of Web Page" with a Show Result, so you can confirm the
real script now produces real output before trusting the full shortcut.

Run:
    python3 examples/fix_remove_diacritics.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Remove Diacritics"
EXTRACTED = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / f"unsigned/{NAME}.shortcut"
EDITED_UNSIGNED = EXTRACTED.with_suffix(".fixed-diagnostic.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (fixed diagnostic).shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

correct_script_action = actions[16]
assert correct_script_action["WFWorkflowActionIdentifier"] == "is.workflow.actions.gettext"
correct_uuid = correct_script_action["WFWorkflowActionParameters"]["UUID"]
assert correct_uuid == "173C7831-9BCA-43E5-B289-92909919D82E"

set_js_action = actions[18]
assert set_js_action["WFWorkflowActionParameters"].get("WFVariableName") == "JavaScript"
set_js_action["WFWorkflowActionParameters"]["WFInput"] = {
    "Value": {"OutputName": "Text", "OutputUUID": correct_uuid, "Type": "ActionOutput"},
    "WFSerializationType": "WFTextTokenAttachment",
}

webpage_index = next(
    i for i, a in enumerate(actions) if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.getwebpagecontents"
)
webpage_uuid = actions[webpage_index]["WFWorkflowActionParameters"]["UUID"]

show_result = action(
    "is.workflow.actions.showresult",
    {
        "Text": {
            "Value": {"OutputName": "Contents of Web Page", "OutputUUID": webpage_uuid, "Type": "ActionOutput"},
            "WFSerializationType": "WFTextTokenAttachment",
        }
    },
)

workflow["WFWorkflowActions"] = actions[: webpage_index + 1] + [show_result]

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed fixed-and-truncated shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it directly (enter text like "
    "'Café Façade'), and report exactly what the result shows."
)
subprocess.run(["open", str(SIGNED)], check=True)
