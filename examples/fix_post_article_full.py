"""Complete, untruncated fix for Post Article -- same two changes as
fix_post_article.py (the diagnostic version), applied to the full
46-action original with the rest of the shortcut (caption picker, Ask,
and all five destination branches) left completely untouched.

Run:
    python3 examples/fix_post_article_full.py
"""

import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Post Article"
EXTRACTED = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / f"unsigned/{NAME}.shortcut"
EDITED_UNSIGNED = EXTRACTED.with_suffix(".fixed-full.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (fixed).shortcut"


def new_uuid():
    return str(uuid.uuid4()).upper()


def variable_ref(name):
    return {"Value": {"Type": "Variable", "VariableName": name}, "WFSerializationType": "WFTextTokenAttachment"}


def output_ref(name, uuid_):
    return {"Value": {"OutputName": name, "OutputUUID": uuid_, "Type": "ActionOutput"}, "WFSerializationType": "WFTextTokenAttachment"}


def set_variable(var_name, value_ref):
    return action("is.workflow.actions.setvariable", {"WFVariableName": var_name, "WFInput": value_ref})


def with_uuid(a, uuid_):
    a["WFWorkflowActionParameters"]["UUID"] = uuid_
    return a


workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

count_index = next(i for i, a in enumerate(actions) if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.count")
richtext_index = next(
    i for i, a in enumerate(actions) if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.getrichtextfromhtml"
)
assert count_index == 4 and richtext_index == 14, (count_index, richtext_index)

richtext_action = actions[richtext_index]

gid = new_uuid()
url_uuid = new_uuid()
expand1_uuid = new_uuid()
linktext1_uuid = new_uuid()
title_uuid = new_uuid()
clip_uuid = new_uuid()
expand2_uuid = new_uuid()
linktext2_uuid = new_uuid()
download_uuid = new_uuid()
getname_uuid = new_uuid()

new_block = [
    action(
        "is.workflow.actions.conditional",
        {
            "GroupingIdentifier": gid,
            "WFCondition": 100,  # Has Any Value
            "WFControlFlowMode": 0,
            "WFInput": {"Type": "Variable", "Variable": variable_ref("Input")},
        },
    ),
    with_uuid(
        action("is.workflow.actions.properties.articles", {"WFContentItemPropertyName": "URL", "WFInput": variable_ref("Input")}),
        url_uuid,
    ),
    with_uuid(action("is.workflow.actions.url.expand", {"URL": output_ref("URL", url_uuid)}), expand1_uuid),
    # Expand's output previews fine but doesn't stringify inside gettext's
    # text combination -- force it through an explicit text coercion first,
    # so Link is a guaranteed plain string everywhere downstream.
    with_uuid(
        action("is.workflow.actions.gettext", {"WFTextActionText": output_ref("Expanded URL", expand1_uuid)}),
        linktext1_uuid,
    ),
    set_variable("Link", output_ref("Text", linktext1_uuid)),
    with_uuid(
        action("is.workflow.actions.properties.articles", {"WFContentItemPropertyName": "Title", "WFInput": variable_ref("Input")}),
        title_uuid,
    ),
    set_variable("Name", output_ref("Title", title_uuid)),
    action("is.workflow.actions.conditional", {"GroupingIdentifier": gid, "WFControlFlowMode": 1}),
    with_uuid(action("is.workflow.actions.getclipboard", {}), clip_uuid),
    with_uuid(action("is.workflow.actions.url.expand", {"URL": output_ref("Clipboard", clip_uuid)}), expand2_uuid),
    with_uuid(
        action("is.workflow.actions.gettext", {"WFTextActionText": output_ref("Expanded URL", expand2_uuid)}),
        linktext2_uuid,
    ),
    set_variable("Link", output_ref("Text", linktext2_uuid)),
    with_uuid(
        action("is.workflow.actions.downloadurl", {"Advanced": True, "ShowHeaders": False, "WFURL": variable_ref("Link")}),
        download_uuid,
    ),
    with_uuid(action("is.workflow.actions.getitemname", {"WFInput": output_ref("Contents of URL", download_uuid)}), getname_uuid),
    set_variable("Name", output_ref("Name", getname_uuid)),
    action("is.workflow.actions.conditional", {"GroupingIdentifier": gid, "WFControlFlowMode": 2}),
]

richtext_action["WFWorkflowActionParameters"]["WFHTML"] = variable_ref("Name")

workflow["WFWorkflowActions"] = actions[:count_index] + new_block + actions[richtext_index:]

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed complete fixed shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it from the Share Sheet, and when "
    "the destination picker appears, choose 'Share...' to test the full flow "
    "without actually posting anywhere."
)
subprocess.run(["open", str(SIGNED)], check=True)
