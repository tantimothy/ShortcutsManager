"""Real fix (not just a diagnostic) for Post Article's broken input handling.

Two changes to the pristine 46-action original:

1. Replace the fragile `If Count [of Input] contains "0"` gate (a substring
   check on a number, WFCondition 99) with `If Input has any value`
   (WFCondition 100, no comparison string needed) -- no ambiguity, no Count.

2. In the "has a value" branch, stop relying on implicit text/URL coercion
   of the shared Article object (confirmed broken: it resolves to nothing).
   Pull URL and Title directly via `Get Details of Article`
   (is.workflow.actions.properties.articles), fed straight from Input.
   The clipboard-fallback branch (Otherwise) keeps the original
   download-and-scrape approach, since clipboard content is plain text/URL,
   not an Article object.

Both branches converge on a common named variable "Name" (the title),
so everything downstream (the existing "Get rich text from HTML" HTML-entity
decode step, the caption picker, and all five destination branches) is left
completely untouched and still wired correctly.

Truncated right after producing Link/Name, with three Show Result diagnostics,
so you can verify the fix before letting it proceed to actually post anywhere.

Run:
    python3 examples/fix_post_article.py
"""

import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut, action

NAME = "Post Article"
EXTRACTED = Path(f"<PROJECTS_DIR>/ShortcutsExtracted/unsigned/{NAME}.shortcut")
EDITED_UNSIGNED = EXTRACTED.with_suffix(".fixed.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (fixed).shortcut"


def new_uuid():
    return str(uuid.uuid4()).upper()


def variable_ref(name):
    return {
        "Value": {"Type": "Variable", "VariableName": name},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def output_ref(name, uuid_):
    return {
        "Value": {"OutputName": name, "OutputUUID": uuid_, "Type": "ActionOutput"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def set_variable(var_name, value_ref):
    return action("is.workflow.actions.setvariable", {"WFVariableName": var_name, "WFInput": value_ref})


workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

# Locate the boundaries of the original Count/If/clipboard/Otherwise/EndIf
# block (indices 4-9) and the getrichtextfromhtml action right after the old
# download chain (index 14), by identifier, matching the known structure.
count_index = next(i for i, a in enumerate(actions) if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.count")
richtext_index = next(
    i for i, a in enumerate(actions) if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.getrichtextfromhtml"
)
assert count_index == 4 and richtext_index == 14, (count_index, richtext_index)

richtext_action = actions[richtext_index]
richtext_uuid = richtext_action["WFWorkflowActionParameters"]["UUID"]

gid = new_uuid()
url_uuid = new_uuid()
expand1_uuid = new_uuid()
title_uuid = new_uuid()
clip_uuid = new_uuid()
expand2_uuid = new_uuid()
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
    # -- If Input has a value: pull URL/Title straight from the Article object.
    (lambda a: (a["WFWorkflowActionParameters"].__setitem__("UUID", url_uuid), a)[1])(
        action(
            "is.workflow.actions.properties.articles",
            {"WFContentItemPropertyName": "URL", "WFInput": variable_ref("Input")},
        )
    ),
    (lambda a: (a["WFWorkflowActionParameters"].__setitem__("UUID", expand1_uuid), a)[1])(
        action("is.workflow.actions.url.expand", {"URL": output_ref("URL", url_uuid)})
    ),
    set_variable("Link", output_ref("Expanded URL", expand1_uuid)),
    (lambda a: (a["WFWorkflowActionParameters"].__setitem__("UUID", title_uuid), a)[1])(
        action(
            "is.workflow.actions.properties.articles",
            {"WFContentItemPropertyName": "Title", "WFInput": variable_ref("Input")},
        )
    ),
    set_variable("Name", output_ref("Title", title_uuid)),
    action("is.workflow.actions.conditional", {"GroupingIdentifier": gid, "WFControlFlowMode": 1}),
    # -- Otherwise: clipboard fallback, same approach as the original.
    (lambda a: (a["WFWorkflowActionParameters"].__setitem__("UUID", clip_uuid), a)[1])(
        action("is.workflow.actions.getclipboard", {})
    ),
    (lambda a: (a["WFWorkflowActionParameters"].__setitem__("UUID", expand2_uuid), a)[1])(
        action("is.workflow.actions.url.expand", {"URL": output_ref("Clipboard", clip_uuid)})
    ),
    set_variable("Link", output_ref("Expanded URL", expand2_uuid)),
    (lambda a: (a["WFWorkflowActionParameters"].__setitem__("UUID", download_uuid), a)[1])(
        action("is.workflow.actions.downloadurl", {"Advanced": True, "ShowHeaders": False, "WFURL": variable_ref("Link")})
    ),
    (lambda a: (a["WFWorkflowActionParameters"].__setitem__("UUID", getname_uuid), a)[1])(
        action("is.workflow.actions.getitemname", {"WFInput": output_ref("Contents of URL", download_uuid)})
    ),
    set_variable("Name", output_ref("Name", getname_uuid)),
    action("is.workflow.actions.conditional", {"GroupingIdentifier": gid, "WFControlFlowMode": 2}),
]

richtext_action["WFWorkflowActionParameters"]["WFHTML"] = variable_ref("Name")

show_input = action("is.workflow.actions.showresult", {"Text": variable_ref("Input")})
show_link = action("is.workflow.actions.showresult", {"Text": variable_ref("Link")})
show_name = action("is.workflow.actions.showresult", {"Text": variable_ref("Name")})

workflow["WFWorkflowActions"] = (
    actions[:count_index]
    + new_block
    + [richtext_action, show_input, show_link, show_name]
)

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed fixed-and-truncated shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, run it from the Share Sheet on a "
    "real article, and report what it shows for Input, Link, and Name."
)
subprocess.run(["open", str(SIGNED)], check=True)
