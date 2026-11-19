"""Builds a safe, non-posting diagnostic copy of "Post Article": keeps every
action up through the point where ActionChoice is set (destination picker),
then shows ActionChoice's raw value/type instead of running any of the five
posting branches. Nothing gets posted anywhere -- this is purely to see what
ActionChoice actually contains after the OS update, since the "contains"
condition on all five branches is silently not matching.

Run after:
    python3 -m shortcuts_manager.cli extract-one --name "Post Article"

    python3 examples/diagnose_post_article.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Post Article"
EXTRACTED = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / f"unsigned/{NAME}.shortcut"
EDITED_UNSIGNED = EXTRACTED.with_suffix(".diagnostic.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (diagnostic).shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

cutoff = None
for i, a in enumerate(actions):
    if a.get("WFWorkflowActionParameters", {}).get("WFVariableName") == "ActionChoice":
        cutoff = i
        break
if cutoff is None:
    raise SystemExit("Couldn't find the action that sets ActionChoice.")

show_choice = action(
    "is.workflow.actions.showresult",
    {
        "Text": {
            "Value": {"Type": "Variable", "VariableName": "ActionChoice"},
            "WFSerializationType": "WFTextTokenAttachment",
        }
    },
)

workflow["WFWorkflowActions"] = actions[: cutoff + 1] + [show_choice]

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed diagnostic shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- click 'Add Shortcut', run the diagnostic copy, "
    "pick your usual destinations, and report what it shows."
)
subprocess.run(["open", str(SIGNED)], check=True)
