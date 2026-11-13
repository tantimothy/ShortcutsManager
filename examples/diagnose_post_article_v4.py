"""v4 diagnostic: shows Input's raw value IMMEDIATELY, as the very first
action after it's set from ExtensionInput -- before openapp, clipboard
fallback, or anything else runs. This sidesteps every downstream failure
and answers directly: what does the Share Sheet actually hand this shortcut?

Built from the pristine 46-action "Post Article", with nothing else touched.

Run after:
    python3 examples/diagnose_post_article_v4.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Post Article"
EXTRACTED = Path(f"<PROJECTS_DIR>/ShortcutsExtracted/unsigned/{NAME}.shortcut")
EDITED_UNSIGNED = EXTRACTED.with_suffix(".diagnostic-v4.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (diagnostic v4).shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

set_input_index = None
for i, a in enumerate(actions):
    if a.get("WFWorkflowActionParameters", {}).get("WFVariableName") == "Input":
        set_input_index = i
        break
if set_input_index is None:
    raise SystemExit("Couldn't find the action that sets Input.")

show_input = action(
    "is.workflow.actions.showresult",
    {"Text": {"Value": {"Type": "Variable", "VariableName": "Input"}, "WFSerializationType": "WFTextTokenAttachment"}},
)

workflow["WFWorkflowActions"] = actions[: set_input_index + 1] + [show_input]

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed diagnostic shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, then run it from the Share Sheet on "
    "the article you'd normally post, and report exactly what it shows."
)
subprocess.run(["open", str(SIGNED)], check=True)
