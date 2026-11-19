"""Audit every extracted shortcut for "Repeat with Each" actions whose
input might be raw multi-line Text rather than an actual list -- the same
shape of bug found in Hashtag List / Dedup List (Shortcuts no longer
auto-splits multi-line Text into one Repeat item per line; an explicit
"Split Text" action is required now).

For each Repeat Each start action, resolves its WFInput back to the
action that actually produced the value (following Set Variable chains a
few hops, since the value flowing into Repeat is often a variable set
earlier, not the Repeat's own literal input), then buckets the result:

  SAFE    -- traced back to something that's definitely already a list
             (Split Text, the List action, or a variable built by
             repeated Append to Variable).
  SUSPECT -- traced back to something that's plain Text and could contain
             embedded newlines with no Split Text in between (Text
             action, Ask for Input, Detect Text, clipboard, a Run
             Shortcut's result, text transforms feeding Repeat directly,
             ExtensionInput).
  UNCLEAR -- couldn't confidently resolve the chain (hit a hop limit, a
             nested Repeat Item, or an unrecognized shape) -- needs a
             manual look.

This is a heuristic static scan, not a runtime trace: branches are
approximated by "nearest preceding Set Variable with this name, scanning
backward from the Repeat", which can be wrong across complex If/Otherwise
logic. Treat SUSPECT/UNCLEAR as a worklist to eyeball in Shortcuts.app,
not as confirmed bugs.

Run:
    python3 examples/audit_repeat_each_split.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import read_shortcut

UNSIGNED_DIR = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted") / "unsigned"

SAFE_IDENTIFIERS = {
    "is.workflow.actions.text.split",
    "is.workflow.actions.list",
    # These already natively produce a list of several items, not a single
    # blob of text -- not the "needs an explicit Split Text" shape at all.
    "is.workflow.actions.detect.images",
    "is.workflow.actions.detect.dictionary",
    "is.workflow.actions.weather.forecast",
    "is.workflow.actions.filter.files",
    "is.workflow.actions.getframesfromimage",
    "is.workflow.actions.getimagefrompdf",
    "is.workflow.actions.documentpicker.open",
}

SUSPECT_IDENTIFIERS = {
    "is.workflow.actions.gettext",
    "is.workflow.actions.ask",
    "is.workflow.actions.detect.text",
    "is.workflow.actions.getclipboard",
    "is.workflow.actions.runworkflow",
    "is.workflow.actions.text.combine",
    "is.workflow.actions.text.replace",
    "is.workflow.actions.text.changecase",
    "is.workflow.actions.gettext.simple",
    "is.workflow.actions.getvalueforkey",
}

MAX_HOPS = 8


def resolve(actions, index, value, appended_names):
    """Follow a WFInput value back to its source. Returns (bucket, trail)."""
    trail = []
    for _ in range(MAX_HOPS):
        if not isinstance(value, dict):
            return "UNCLEAR", trail + [f"non-dict value: {value!r}"]
        vtype = value.get("Type")

        if vtype == "ExtensionInput":
            trail.append("ExtensionInput")
            return "SUSPECT", trail

        if vtype == "ActionOutput":
            uuid = value.get("OutputUUID")
            src = next(
                (a for a in actions if a.get("WFWorkflowActionParameters", {}).get("UUID") == uuid),
                None,
            )
            if src is None:
                trail.append(f"ActionOutput {uuid} -- source action not found")
                return "UNCLEAR", trail
            ident = src["WFWorkflowActionIdentifier"]
            if ident == "is.workflow.actions.getvalueforkey":
                kind = src["WFWorkflowActionParameters"].get("WFGetDictionaryValueType")
                if kind in ("All Keys", "All Values"):
                    trail.append(f"ActionOutput -> getvalueforkey ({kind}) -- already a list")
                    return "SAFE", trail
                trail.append(f"ActionOutput -> getvalueforkey (single key) -- could be any type")
                return "SUSPECT", trail
            trail.append(f"ActionOutput -> {ident}")
            if ident in SAFE_IDENTIFIERS:
                return "SAFE", trail
            if ident in SUSPECT_IDENTIFIERS:
                return "SUSPECT", trail
            return "UNCLEAR", trail

        if vtype == "Variable":
            name = value.get("VariableName")
            if name == "Repeat Item":
                trail.append("Repeat Item (nested repeat) -- not traced")
                return "UNCLEAR", trail
            if name in appended_names:
                trail.append(f"Variable '{name}' -- built via Append to Variable")
                return "SAFE", trail
            # nearest preceding Set Variable with this name
            setter = None
            for a in reversed(actions[:index]):
                if (
                    a.get("WFWorkflowActionIdentifier") == "is.workflow.actions.setvariable"
                    and a.get("WFWorkflowActionParameters", {}).get("WFVariableName") == name
                ):
                    setter = a
                    break
            if setter is None:
                trail.append(f"Variable '{name}' -- no Set Variable found (ExtensionInput default? loop var?)")
                return "UNCLEAR", trail
            trail.append(f"Variable '{name}' <- Set Variable")
            value = setter["WFWorkflowActionParameters"].get("WFInput", {}).get("Value")
            continue

        trail.append(f"unrecognized Type: {vtype!r}")
        return "UNCLEAR", trail

    trail.append("hop limit reached")
    return "UNCLEAR", trail


def audit_workflow(name, actions):
    appended_names = {
        a["WFWorkflowActionParameters"].get("WFVariableName")
        for a in actions
        if a.get("WFWorkflowActionIdentifier") == "is.workflow.actions.appendvariable"
    }
    results = []
    for i, a in enumerate(actions):
        if a.get("WFWorkflowActionIdentifier") != "is.workflow.actions.repeat.each":
            continue
        if a.get("WFWorkflowActionParameters", {}).get("WFControlFlowMode") != 0:
            continue
        wf_input = a.get("WFWorkflowActionParameters", {}).get("WFInput")
        if wf_input is None:
            # No explicit input -- Shortcuts implicitly pipes in the
            # previous action's output.
            if i == 0:
                bucket, trail = "UNCLEAR", ["no WFInput and no previous action"]
            else:
                prev = actions[i - 1]
                ident = prev["WFWorkflowActionIdentifier"]
                if ident == "is.workflow.actions.getvariable":
                    # Transparent passthrough -- keep following the chain
                    # via whatever variable it's getting, same as if the
                    # Repeat had referenced that variable directly.
                    inner = prev["WFWorkflowActionParameters"].get("WFVariable", {}).get("Value")
                    bucket, trail = resolve(actions, i, inner, appended_names)
                    trail = ["implicit (no WFInput) <- previous Get Variable"] + trail
                else:
                    trail = [f"implicit (no WFInput) <- previous action {ident}"]
                    if ident in SAFE_IDENTIFIERS:
                        bucket = "SAFE"
                    elif ident in SUSPECT_IDENTIFIERS:
                        bucket = "SUSPECT"
                    else:
                        bucket = "UNCLEAR"
        else:
            value = wf_input.get("Value")
            bucket, trail = resolve(actions, i, value, appended_names)
        results.append((i, bucket, trail))
    return results


def main():
    counts = {"SAFE": 0, "SUSPECT": 0, "UNCLEAR": 0}
    suspect_or_unclear = []

    for path in sorted(UNSIGNED_DIR.glob("*.shortcut")):
        try:
            wf = read_shortcut(path)
        except Exception as e:
            print(f"SKIP {path.name}: {e}")
            continue
        actions = wf.get("WFWorkflowActions") or []
        if not actions:
            continue
        for i, bucket, trail in audit_workflow(path.stem, actions):
            counts[bucket] += 1
            if bucket != "SAFE":
                suspect_or_unclear.append((path.stem, i, bucket, trail))

    print(f"Repeat Each actions scanned: {sum(counts.values())}")
    print(f"  SAFE:    {counts['SAFE']}")
    print(f"  SUSPECT: {counts['SUSPECT']}")
    print(f"  UNCLEAR: {counts['UNCLEAR']}")
    print()
    print("Worklist (SUSPECT + UNCLEAR), one per Repeat Each action:")
    print()
    for name, i, bucket, trail in suspect_or_unclear:
        print(f"[{bucket}] {name}  (action index {i})")
        for line in trail:
            print(f"    {line}")


if __name__ == "__main__":
    main()
