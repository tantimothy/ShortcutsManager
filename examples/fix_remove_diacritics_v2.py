"""v2: same rewiring fix as fix_remove_diacritics.py, but stops one step
earlier and shows Input Text + the fully-constructed JavaScript string
(the actual script about to be embedded in the data: URL), before it ever
reaches the web view. Isolates whether the problem is upstream (Input
Text never captured) or in the script substitution/execution itself.

Run:
    python3 examples/fix_remove_diacritics_v2.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Remove Diacritics"
EXTRACTED = Path(f"<PROJECTS_DIR>/ShortcutsExtracted/unsigned/{NAME}.shortcut")
EDITED_UNSIGNED = EXTRACTED.with_suffix(".fixed-diagnostic-v2.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (fixed diagnostic v2).shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

correct_uuid = "173C7831-9BCA-43E5-B289-92909919D82E"
set_js_action = actions[18]
assert set_js_action["WFWorkflowActionParameters"].get("WFVariableName") == "JavaScript"
set_js_action["WFWorkflowActionParameters"]["WFInput"] = {
    "Value": {"OutputName": "Text", "OutputUUID": correct_uuid, "Type": "ActionOutput"},
    "WFSerializationType": "WFTextTokenAttachment",
}

def variable_ref(name):
    return {"Value": {"Type": "Variable", "VariableName": name}, "WFSerializationType": "WFTextTokenAttachment"}

show_input_text = action("is.workflow.actions.showresult", {"Text": variable_ref("Input Text")})
show_javascript = action("is.workflow.actions.showresult", {"Text": variable_ref("JavaScript")})

workflow["WFWorkflowActions"] = actions[:19] + [show_input_text, show_javascript]

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed diagnostic shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it directly, type in text like "
    "'Café Façade' when asked, and report both results exactly (the second "
    "one will be long -- just check it starts/ends sensibly and that your "
    "text appears correctly near the end)."
)
subprocess.run(["open", str(SIGNED)], check=True)
