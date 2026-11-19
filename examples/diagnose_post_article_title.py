"""v2 diagnostic: drops WFArticleContentItem from the accepted Share Sheet
input classes (matching the fix for the "Expand URL ... Rich Text" error),
then stops right after the title-extraction chain (download the URL, get its
item name) and shows Input / Link / Name instead of continuing to the
destination picker or posting anywhere.

Run after:
    python3 -m shortcuts_manager.cli extract-one --name "Post Article"

    python3 examples/diagnose_post_article_title.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Post Article"
EXTRACTED = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / f"unsigned/{NAME}.shortcut"
EDITED_UNSIGNED = EXTRACTED.with_suffix(".diagnostic-title.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (diagnostic title).shortcut"


def output_ref(name, uuid):
    return {
        "Value": {"OutputName": name, "OutputUUID": uuid, "Type": "ActionOutput"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def variable_ref(name):
    return {
        "Value": {"Type": "Variable", "VariableName": name},
        "WFSerializationType": "WFTextTokenAttachment",
    }


workflow = read_shortcut(EXTRACTED)
workflow["WFWorkflowInputContentItemClasses"] = [
    "WFSafariWebPageContentItem",
    "WFURLContentItem",
]

actions = workflow["WFWorkflowActions"]

# Find "Get name of" (is.workflow.actions.getitemname) -- its UUID is the
# OutputUUID that downstream actions reference as "Name".
name_action_index = None
name_output_uuid = None
for i, a in enumerate(actions):
    if a.get("WFWorkflowActionIdentifier") == "is.workflow.actions.getitemname":
        name_action_index = i
        name_output_uuid = a["WFWorkflowActionParameters"]["UUID"]
        break
if name_action_index is None:
    raise SystemExit("Couldn't find the 'Get name of' action.")

show_input = action("is.workflow.actions.showresult", {"Text": variable_ref("Input")})
show_link = action("is.workflow.actions.showresult", {"Text": variable_ref("Link")})
show_name = action(
    "is.workflow.actions.showresult",
    {"Text": output_ref("Name", name_output_uuid)},
)

workflow["WFWorkflowActions"] = (
    actions[: name_action_index + 1] + [show_input, show_link, show_name]
)

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed diagnostic shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, then run it from the Share Sheet on "
    "the article you'd normally post, and report the three values it shows "
    "(Input, Link, Name)."
)
subprocess.run(["open", str(SIGNED)], check=True)
