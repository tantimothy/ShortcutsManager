"""The complete, real fix for "Remove Diacritics" -- two bugs, both confirmed
empirically against the real shortcut running on-device:

1. "Set Variable 'JavaScript'" (action 18) was wired to a broken, orphaned
   92-char script (action 17 -- discards its own computed result and calls
   completion(result) with an undefined `result`) instead of the complete,
   correct 9086-char removeDiacritics() script sitting unused right next to
   it (action 16, which document.write()s its result).

2. That correct script (action 16) embeds the raw "{Input Text}" variable
   directly into a double-quoted JS string literal:
       var paragraph = "{Input Text}";
   Any literal newline in the input breaks that string (unterminated
   string literal), silently killing the whole script -- which is exactly
   why multi-line input produced blank output even after fix #1, while
   single-line input worked. The shortcut *already* has a step for this
   (action 15: Replace Text, turns \n into <br> in "Input Text", producing
   "Updated Text") -- it's just never used downstream. Action 16 should
   reference "Updated Text" instead of "Input Text".

   (Note: this does not protect against a literal double-quote in the
   input, which would still break the string the same way -- that risk
   already existed in the original shortcut and is out of scope here.)

This builds the full, non-diagnostic shortcut -- every original action
intact, both fixes applied -- signed as "Remove Diacritics (fixed)".

Run:
    python3 examples/fix_remove_diacritics_complete.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut

NAME = "Remove Diacritics"
EXTRACTED = Path(f"<PROJECTS_DIR>/ShortcutsExtracted/unsigned/{NAME}.shortcut")
EDITED_UNSIGNED = EXTRACTED.with_suffix(".fixed-complete.shortcut")
SIGNED = Path(__file__).resolve().parent / "REMOVE DIACRITICS - REAL FIX.shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

# Fix 1: rewire "Set Variable 'JavaScript'" to the correct, complete script.
correct_uuid = "173C7831-9BCA-43E5-B289-92909919D82E"
set_js_action = actions[18]
assert set_js_action["WFWorkflowActionParameters"].get("WFVariableName") == "JavaScript"
set_js_action["WFWorkflowActionParameters"]["WFInput"] = {
    "Value": {"OutputName": "Text", "OutputUUID": correct_uuid, "Type": "ActionOutput"},
    "WFSerializationType": "WFTextTokenAttachment",
}

# Fix 2: inside that correct script, swap the embedded "Input Text" reference
# for action 15's output (display name "Updated Text") -- the already-
# computed, newline-safe version. "Updated Text" is NOT a named variable
# (no Set Variable action creates it); it's only the auto-generated output
# label of the Replace Text action, so it must be referenced as an
# ActionOutput-by-UUID, exactly like the original broken script (action 17)
# already correctly did -- not as {"Type": "Variable", ...}.
replace_action = actions[15]
assert replace_action["WFWorkflowActionIdentifier"] == "is.workflow.actions.text.replace"
updated_text_uuid = replace_action["WFWorkflowActionParameters"]["UUID"]
assert updated_text_uuid == "E60A0CB2-828A-41EB-A1CC-AE94F054815E"

script_action = actions[16]
assert script_action["WFWorkflowActionIdentifier"] == "is.workflow.actions.gettext"
assert script_action["WFWorkflowActionParameters"]["UUID"] == correct_uuid
script_text = script_action["WFWorkflowActionParameters"]["WFTextActionText"]
attachments = script_text["Value"]["attachmentsByRange"]
found = False
for key, attachment in attachments.items():
    if attachment.get("VariableName") == "Input Text":
        attachment.clear()
        attachment["Type"] = "ActionOutput"
        attachment["OutputName"] = "Updated Text"
        attachment["OutputUUID"] = updated_text_uuid
        found = True
assert found, "Couldn't find the 'Input Text' reference inside the script to fix"

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed fixed shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it, type multi-line accented "
    "text (e.g. the default example), and confirm the final alert shows "
    "correct diacritics-stripped output."
)
subprocess.run(["open", str(SIGNED)], check=True)
