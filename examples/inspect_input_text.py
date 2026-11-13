"""Single unambiguous test: shows "Input Text" itself, right after it's set
(before the trim/replace steps), with nothing else. Isolates whether the
Ask/branching logic is correctly capturing multi-line typed text at all,
before blaming the Replace Text step.

Run:
    python3 examples/inspect_input_text.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Remove Diacritics"
EXTRACTED = Path(f"<PROJECTS_DIR>/ShortcutsExtracted/unsigned/{NAME}.shortcut")
EDITED_UNSIGNED = EXTRACTED.with_suffix(".inspect-input-text.shortcut")
SIGNED = Path(__file__).resolve().parent / "INSPECT INPUT TEXT.shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

end_if = actions[13]
assert end_if["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
assert end_if["WFWorkflowActionParameters"].get("WFControlFlowMode") == 2

def variable_ref(name):
    return {"Value": {"Type": "Variable", "VariableName": name}, "WFSerializationType": "WFTextTokenAttachment"}

show_result = action("is.workflow.actions.showresult", {"Text": variable_ref("Input Text")})

workflow["WFWorkflowActions"] = actions[:14] + [show_result]

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed test shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it, type/accept the default "
    "multi-line example text, and report EXACTLY what the single popup shows."
)
subprocess.run(["open", str(SIGNED)], check=True)
