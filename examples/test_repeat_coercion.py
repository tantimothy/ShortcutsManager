"""Isolated test of the actual claim: does "Repeat with Each" over a
multi-line Text value iterate once per line by default, and does adding a
"Text" type-coercion Aggrandizement (the same one found in "Dedup List")
change that to one single iteration over the whole blob?

Builds TWO minimal shortcuts:
  - REPEAT TEST (no coercion): Text "Line1\nLine2\nLine3" -> Repeat Each ->
    append each Repeat Item to a list -> show the resulting list.
  - REPEAT TEST (with coercion): identical, but the Repeat's input carries
    the same WFStringContentItem coercion Aggrandizement we found in the
    real "Dedup List" bug.

If the no-coercion version shows 3 items and the coercion version shows 1
item (the whole blob), that confirms the real-world fix. If not, the real
bug is something else and we should not trust the "Dedup List (fixed)"
change.

Run:
    python3 examples/test_repeat_coercion.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, action, read_shortcut

LINES = "Line1\nLine2\nLine3"

# Reuse a real, known-good shortcut's top-level workflow dict (icon, client
# version, import questions, etc.) instead of hand-building one from
# scratch -- a from-scratch workflow dict seems to have its own reliability
# issues showing freshly-introduced variables via Show Result, independent
# of anything to do with coercion, so only WFWorkflowActions is replaced.
TEMPLATE = Path("<PROJECTS_DIR>/ShortcutsExtracted/unsigned/Dedup List.shortcut")


def build(name, with_coercion):
    text_action = action("is.workflow.actions.gettext", {"WFTextActionText": LINES})
    text_uuid = "11111111-1111-1111-1111-111111111111"
    text_action["WFWorkflowActionParameters"]["UUID"] = text_uuid

    repeat_input_value = {"Type": "ActionOutput", "OutputName": "Text", "OutputUUID": text_uuid}
    if with_coercion:
        repeat_input_value["Aggrandizements"] = [
            {"CoercionItemClass": "WFStringContentItem", "Type": "WFCoercionVariableAggrandizement"}
        ]

    grouping = "22222222-2222-2222-2222-222222222222"
    repeat_start = action(
        "is.workflow.actions.repeat.each",
        {
            "WFControlFlowMode": 0,
            "GroupingIdentifier": grouping,
            "WFInput": {"Value": repeat_input_value, "WFSerializationType": "WFTextTokenAttachment"},
        },
    )

    def variable_ref(name):
        return {"Value": {"Type": "Variable", "VariableName": name}, "WFSerializationType": "WFTextTokenAttachment"}

    repeat_item_ref = {
        "Value": {"Type": "Variable", "VariableName": "Repeat Item"},
        "WFSerializationType": "WFTextTokenAttachment",
    }
    append_action = action(
        "is.workflow.actions.appendvariable",
        {"WFVariableName": "Items", "WFInput": repeat_item_ref},
    )

    repeat_end = action(
        "is.workflow.actions.repeat.each",
        {"WFControlFlowMode": 2, "GroupingIdentifier": grouping},
    )

    show_result = action("is.workflow.actions.showresult", {"Text": variable_ref("Items")})

    workflow = read_shortcut(TEMPLATE)
    workflow["WFWorkflowActions"] = [text_action, repeat_start, append_action, repeat_end, show_result]

    unsigned = Path(__file__).resolve().parent / f"{name}.unsigned.shortcut"
    signed = Path(__file__).resolve().parent / f"{name}.shortcut"
    write_unsigned(workflow, unsigned)
    sign(unsigned, signed, mode="anyone")
    unsigned.unlink()
    return signed


no_coercion = build("REPEAT TEST (no coercion)", with_coercion=False)
with_coercion = build("REPEAT TEST (with coercion)", with_coercion=True)

print(f"Built: {no_coercion}")
print(f"Built: {with_coercion}")
print("Opening both in Shortcuts.app -- run each one (no input needed, text is hardcoded), and report exactly what each one's single popup shows.")
subprocess.run(["open", str(no_coercion)], check=True)
subprocess.run(["open", str(with_coercion)], check=True)
