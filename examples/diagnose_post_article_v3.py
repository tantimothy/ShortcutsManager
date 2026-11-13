"""v3 diagnostic, built from the pristine 46-action "Post Article" (not the
hand-edited copies, which lost an action during manual editing). Inserts
"Get Details of Article" (WFContentItemPropertyName: "URL") between the
Input/clipboard If-block and "Expand", using the real action identifier
confirmed from the user's own edited copy (is.workflow.actions.properties.articles).
Leaves the existing download-based title chain (downloadurl -> getitemname ->
getrichtextfromhtml) untouched, to isolate whether fixing the URL alone is
enough. Stops right after that chain and shows Input / Link / Name instead of
continuing to the destination picker or posting anywhere.

Run after:
    python3 -m shortcuts_manager.cli extract-one --name "Post Article"
    (already done earlier in this session -- the pristine extract is reused)

    python3 examples/diagnose_post_article_v3.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Post Article"
EXTRACTED = Path(f"<PROJECTS_DIR>/ShortcutsExtracted/unsigned/{NAME}.shortcut")
EDITED_UNSIGNED = EXTRACTED.with_suffix(".diagnostic-v3.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (diagnostic v3).shortcut"


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
actions = workflow["WFWorkflowActions"]

# Locate the End If (WFControlFlowMode 2) closing the Input/clipboard block,
# and the Expand action right after it, by their known UUIDs in this file.
end_if_index = None
end_if_uuid = None
expand_index = None
for i, a in enumerate(actions):
    params = a.get("WFWorkflowActionParameters", {})
    if (
        a.get("WFWorkflowActionIdentifier") == "is.workflow.actions.conditional"
        and params.get("WFControlFlowMode") == 2
        and "GroupingIdentifier" in params
        and end_if_index is None
    ):
        end_if_index = i
        end_if_uuid = params["UUID"]
    if a.get("WFWorkflowActionIdentifier") == "is.workflow.actions.url.expand":
        expand_index = i
        break

if end_if_index is None or expand_index is None:
    raise SystemExit("Couldn't locate the End If / Expand actions.")

get_article_url = action(
    "is.workflow.actions.properties.articles",
    {
        "WFContentItemPropertyName": "URL",
        "WFInput": output_ref("If Result", end_if_uuid),
    },
)
get_article_url["WFWorkflowActionParameters"]["UUID"] = "D6B8F2A1-0000-4000-8000-000000000001"
article_url_uuid = get_article_url["WFWorkflowActionParameters"]["UUID"]

# Rewrite Expand's input to come from the new action instead of "If Result".
expand_action = actions[expand_index]
expand_action["WFWorkflowActionParameters"]["URL"] = {
    "Value": {
        "attachmentsByRange": {"{0, 1}": {"OutputName": "URL", "OutputUUID": article_url_uuid, "Type": "ActionOutput"}},
        "string": "￼",
    },
    "WFSerializationType": "WFTextTokenString",
}

# Find "Get name of" to know where the title chain ends.
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
show_name = action("is.workflow.actions.showresult", {"Text": output_ref("Name", name_output_uuid)})

new_actions = (
    actions[: expand_index]
    + [get_article_url]
    + actions[expand_index : name_action_index + 1]
    + [show_input, show_link, show_name]
)
workflow["WFWorkflowActions"] = new_actions

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
