"""ONE unambiguous test shortcut, replacing every earlier diagnostic/fix
attempt. Distinctly named so it can't be confused with any shortcut already
on the device.

What it does:
  1. Applies the one-line rewiring fix: "Set Variable 'JavaScript'" (action
     18) now reads from the complete, correct script (action 16) instead of
     the broken one (action 17).
  2. Keeps the ENTIRE original pipeline intact up through the point where
     "Output Text" is computed (this includes the real data: URL web-view
     JavaScript execution step -- nothing is skipped or truncated early).
  3. Stops there and shows exactly ONE result: a single popup reading
     "Input: <text>\n\nOutput: <text>". No other shortcut, no other popup,
     nothing else to tap through.

Run:
    python3 examples/fix_remove_diacritics_final.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Remove Diacritics"
EXTRACTED = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / f"unsigned/{NAME}.shortcut"
EDITED_UNSIGNED = EXTRACTED.with_suffix(".final-test.shortcut")
SIGNED = Path(__file__).resolve().parent / "DIACRITICS FINAL TEST.shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

correct_uuid = "173C7831-9BCA-43E5-B289-92909919D82E"
set_js_action = actions[18]
assert set_js_action["WFWorkflowActionParameters"].get("WFVariableName") == "JavaScript"
set_js_action["WFWorkflowActionParameters"]["WFInput"] = {
    "Value": {"OutputName": "Text", "OutputUUID": correct_uuid, "Type": "ActionOutput"},
    "WFSerializationType": "WFTextTokenAttachment",
}

output_text_action = actions[25]
assert output_text_action["WFWorkflowActionIdentifier"] == "is.workflow.actions.setvariable"
assert output_text_action["WFWorkflowActionParameters"].get("WFVariableName") == "Output Text"

template = "Input: ￼\n\nOutput: ￼"
input_pos = template.index("￼")
output_pos = template.index("￼", input_pos + 1)

result_text = {
    "Value": {
        "string": template,
        "attachmentsByRange": {
            "{%d, 1}" % input_pos: {"Type": "Variable", "VariableName": "Input Text"},
            "{%d, 1}" % output_pos: {"Type": "Variable", "VariableName": "Output Text"},
        },
    },
    "WFSerializationType": "WFTextTokenString",
}

show_result = action("is.workflow.actions.showresult", {"Text": result_text})

workflow["WFWorkflowActions"] = actions[:26] + [show_result]

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed test shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- this is the ONLY one to run. Add it, tap it "
    "to RUN (not edit), type text like 'Café Façade' when asked, and report "
    "exactly what the one and only popup shows."
)
subprocess.run(["open", str(SIGNED)], check=True)
