"""Diagnostic copy of "Remove Diacritics": stops right after "Get Contents
of Web Page" (which loads a data:text/html,<script>...</script> URL in a
hidden web view to run embedded JavaScript) and shows its raw result,
instead of continuing to Detect Text / Show Alert. If the output is blank,
WebKit is refusing to execute the embedded script from a data: URI --
this isolates that from everything downstream.

Run:
    python3 examples/diagnose_remove_diacritics.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Remove Diacritics"
EXTRACTED = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / f"unsigned/{NAME}.shortcut"
EDITED_UNSIGNED = EXTRACTED.with_suffix(".diagnostic.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (diagnostic).shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

webpage_index = None
webpage_uuid = None
for i, a in enumerate(actions):
    if a.get("WFWorkflowActionIdentifier") == "is.workflow.actions.getwebpagecontents":
        webpage_index = i
        webpage_uuid = a["WFWorkflowActionParameters"]["UUID"]
        break
if webpage_index is None:
    raise SystemExit("Couldn't find the 'Get Contents of Web Page' action.")

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
print(f"Signed diagnostic shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it directly (it'll ask you for "
    "text, e.g. 'Café Façade'), and report exactly what the result shows."
)
subprocess.run(["open", str(SIGNED)], check=True)
