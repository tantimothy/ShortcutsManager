"""Fix for "Dedup List" (called internally by "Hashtag List" and possibly
others): the "Repeat with each item in {IncomingList}" step (action 2) has
a type-coercion Aggrandizement on its input --

    "Aggrandizements": [{"CoercionItemClass": "WFStringContentItem",
                          "Type": "WFCoercionVariableAggrandizement"}]

-- which forces IncomingList to be flattened into a single plain string
before the loop runs. That overrides Shortcuts' normal behavior of
auto-splitting a multi-line Text value into one Repeat item per line, which
is exactly the reported symptom: the whole multi-line input becomes "one
item" in the repeat instead of one item per line.

Fix: remove that Aggrandizement so the Repeat Each step receives the value
in its natural (unflattened) form again.

Run:
    python3 examples/fix_dedup_list.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import write_unsigned, sign, read_shortcut

NAME = "Dedup List"
EXTRACTED = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / f"unsigned/{NAME}.shortcut"
EDITED_UNSIGNED = EXTRACTED.with_suffix(".fixed.shortcut")
SIGNED = Path(__file__).resolve().parent / f"{NAME} (fixed).shortcut"

workflow = read_shortcut(EXTRACTED)
actions = workflow["WFWorkflowActions"]

repeat_start = actions[2]
assert repeat_start["WFWorkflowActionIdentifier"] == "is.workflow.actions.repeat.each"
wf_input = repeat_start["WFWorkflowActionParameters"]["WFInput"]
value = wf_input["Value"]
assert value.get("VariableName") == "IncomingList"
removed = value.pop("Aggrandizements", None)
assert removed is not None, "No Aggrandizements found to remove -- already fixed?"
print("Removed aggrandizement:", removed)

write_unsigned(workflow, EDITED_UNSIGNED)
sign(EDITED_UNSIGNED, SIGNED, mode="anyone")
EDITED_UNSIGNED.unlink()
print(f"Signed fixed shortcut written: {SIGNED}")
print(
    "Opening in Shortcuts.app -- add it, replace your real 'Dedup List' "
    "action list with this one (or just test it standalone with multi-line "
    "text as input), and confirm it now dedups per-line instead of "
    "treating the whole block as one item."
)
subprocess.run(["open", str(SIGNED)], check=True)
