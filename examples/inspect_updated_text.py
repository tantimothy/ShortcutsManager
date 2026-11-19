"""Single unambiguous test: shows exactly what "Updated Text" (the result of
replacing \\n with <br> in Input Text) looks like after a real run, with no
other actions, no JS, nothing else. Isolates whether the newline-to-<br>
substitution is actually happening as expected.

Run:
    python3 examples/inspect_updated_text.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Remove Diacritics"
EXTRACTED = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / f"unsigned/{NAME}.shortcut"
EDITED_UNSIGNED = EXTRACTED.with_suffix(".inspect-updated-text.shortcut")
SIGNED = Path(__file__).resolve().parent / "INSPECT UPDATED TEXT.shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

replace_action = actions[15]
assert replace_action["WFWorkflowActionIdentifier"] == "is.workflow.actions.text.replace"

def variable_ref(name):
    return {"Value": {"Type": "Variable", "VariableName": name}, "WFSerializationType": "WFTextTokenAttachment"}

show_result = action("is.workflow.actions.showresult", {"Text": variable_ref("Updated Text")})

workflow["WFWorkflowActions"] = actions[:16] + [show_result]

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed test shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it, type/accept the default "
    "multi-line example text, and report EXACTLY what the single popup "
    "shows (does it contain literal <br> text where the line breaks were?)."
)
subprocess.run(["open", str(SIGNED)], check=True)
