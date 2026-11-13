"""Read-only access to the Shortcuts app's local Core Data/SQLite library.

The real library is ~/Library/Shortcuts/Shortcuts.sqlite. The Group
Containers (group.com.apple.shortcuts, group.is.workflow.shortcuts) also
hold *.sqlite files, but under Temporary/.../ProgressiveMigration/ those
are empty CloudKit migration scratch databases, confirmed by inspection --
kept here only as a fallback/cross-check, not the primary source.

This never writes to the store -- it's undocumented and versioned per-OS
(see README.md). Requires Full Disk Access for whatever process runs this.
"""

import base64
import json
import plistlib
import sqlite3
from datetime import datetime, date
from pathlib import Path

from . import nsarchive

GROUP_CONTAINERS = [
    "group.com.apple.shortcuts",
    "group.is.workflow.shortcuts",
]

# The actual library (confirmed by exploration: ~/Library/Shortcuts/Shortcuts.sqlite
# holds real rows; the Group Containers' Temporary/*.sqlite files are empty
# CloudKit migration scratch databases) lives directly under ~/Library/Shortcuts,
# not in a Group Container.
LIBRARY_DIRS = [
    "Shortcuts",
]


def find_stores():
    """Every *.sqlite file under the Shortcuts library dir and Group Containers."""
    home = Path.home()
    stores = []
    for name in LIBRARY_DIRS:
        base = home / "Library" / name
        if base.exists():
            stores.extend(sorted(base.rglob("*.sqlite")))
    for name in GROUP_CONTAINERS:
        base = home / "Library" / "Group Containers" / name
        if base.exists():
            stores.extend(sorted(base.rglob("*.sqlite")))
    return stores


def _connect(db_path):
    # mode=ro: never write to the user's live Shortcuts library.
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def inspect_schema(db_path):
    """{table_name: {"columns": [...], "row_count": n}} for one store."""
    con = _connect(db_path)
    try:
        cur = con.cursor()
        tables = [
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        schema = {}
        for table in tables:
            cols = [
                {"name": r[1], "type": r[2]}
                for r in cur.execute(f"PRAGMA table_info('{table}')")
            ]
            (count,) = cur.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()
            schema[table] = {"columns": cols, "row_count": count}
        return schema
    finally:
        con.close()


def _decode_blob(data):
    """Best-effort decode of a BLOB column: NSKeyedArchiver, then plain
    plist, then give up and return it base64-encoded."""
    unarchived = nsarchive.loads(data)
    if unarchived is not None:
        return {"$decoded": "nskeyedarchiver", "value": unarchived}
    try:
        return {"$decoded": "plist", "value": plistlib.loads(data)}
    except Exception:
        pass
    return {"$decoded": "raw-base64", "value": base64.b64encode(data).decode("ascii")}


def _row_to_dict(row, columns):
    out = {}
    for value, col in zip(row, columns):
        if isinstance(value, bytes):
            out[col] = _decode_blob(value)
        else:
            out[col] = value
    return out


def dump_raw(db_path, out_dir):
    """Dump every table of one store to <out_dir>/<db_stem>/<table>.json."""
    db_path = Path(db_path)
    out_dir = Path(out_dir) / db_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    schema = inspect_schema(db_path)
    con = _connect(db_path)
    try:
        cur = con.cursor()
        for table, info in schema.items():
            col_names = [c["name"] for c in info["columns"]]
            rows = cur.execute(f"SELECT * FROM '{table}'").fetchall()
            records = [_row_to_dict(row, col_names) for row in rows]
            (out_dir / f"{table}.json").write_text(
                json.dumps(records, indent=2, default=_json_default)
            )
    finally:
        con.close()
    return out_dir


def find_main_store():
    """The real library store, ~/Library/Shortcuts/Shortcuts.sqlite, if present."""
    for store in find_stores():
        if store.name == "Shortcuts.sqlite" and store.parent.name == "Shortcuts":
            return store
    return None


def _decode_value(data):
    """Like _decode_blob, but returns the bare value (for reassembling a
    WFWorkflow dict) instead of the {"$decoded": ...} inspection wrapper."""
    unarchived = nsarchive.loads(data)
    if unarchived is not None:
        return unarchived
    try:
        return plistlib.loads(data)
    except Exception:
        return data


def list_shortcuts(db_path=None):
    """[{"name", "workflow_id", "action_count", "subtitle"}, ...] for every
    non-deleted shortcut, ordered by name."""
    db_path = db_path or find_main_store()
    if db_path is None:
        raise FileNotFoundError("No Shortcuts library store found.")
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT ZNAME, ZWORKFLOWID, ZACTIONCOUNT, ZWORKFLOWSUBTITLE "
            "FROM ZSHORTCUT WHERE ZTOMBSTONED = 0 AND ZCONFLICTOF IS NULL "
            "ORDER BY ZNAME"
        ).fetchall()
        return [
            {"name": r[0], "workflow_id": r[1], "action_count": r[2], "subtitle": r[3]}
            for r in rows
        ]
    finally:
        con.close()


def extract_workflow(name, db_path=None):
    """Reconstruct a WFWorkflow dict for the shortcut named `name`, by
    joining ZSHORTCUT -> ZSHORTCUTACTIONS (the actions array) ->
    ZSHORTCUTICON (icon color/glyph). The result is shaped exactly like
    workflow.new_workflow()'s output -- pass it straight to
    write_unsigned()/sign() to produce an editable, re-importable
    .shortcut file. Returns None if no such (non-tombstoned) shortcut
    exists.
    """
    db_path = db_path or find_main_store()
    if db_path is None:
        raise FileNotFoundError("No Shortcuts library store found.")
    con = _connect(db_path)
    try:
        cur = con.cursor()
        row = cur.execute(
            "SELECT * FROM ZSHORTCUT WHERE ZNAME = ? AND ZTOMBSTONED = 0 "
            "AND ZCONFLICTOF IS NULL LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        shortcut = dict(zip(cols, row))

        actions = []
        if shortcut.get("ZACTIONS") is not None:
            arow = cur.execute(
                "SELECT ZDATA FROM ZSHORTCUTACTIONS WHERE Z_PK = ?",
                (shortcut["ZACTIONS"],),
            ).fetchone()
            if arow and arow[0] is not None:
                actions = _decode_value(arow[0]) or []

        icon = {"WFWorkflowIconStartColor": 4282601983, "WFWorkflowIconGlyphNumber": 61440}
        if shortcut.get("ZICON") is not None:
            irow = cur.execute(
                "SELECT ZBACKGROUNDCOLORVALUE, ZGLYPHNUMBER FROM ZSHORTCUTICON WHERE Z_PK = ?",
                (shortcut["ZICON"],),
            ).fetchone()
            if irow:
                icon = {
                    "WFWorkflowIconStartColor": irow[0],
                    "WFWorkflowIconGlyphNumber": irow[1],
                }

        def decoded(col):
            value = shortcut.get(col)
            if value is None:
                return None
            return _decode_value(value) if isinstance(value, bytes) else value

        workflow = {
            "WFWorkflowActions": actions,
            "WFWorkflowIcon": icon,
            "WFWorkflowTypes": [],
            "WFWorkflowInputContentItemClasses": decoded("ZINPUTCLASSESDATA") or [],
            "WFWorkflowImportQuestions": decoded("ZIMPORTQUESTIONSDATA") or [],
            "WFWorkflowOutputContentItemClasses": decoded("ZOUTPUTCLASSESDATA") or [],
            "WFWorkflowHasOutputFallback": bool(shortcut.get("ZHASOUTPUTFALLBACK")),
            "WFWorkflowHasShortcutInputVariables": bool(
                shortcut.get("ZHASSHORTCUTINPUTVARIABLES")
            ),
        }
        if shortcut.get("ZMINIMUMCLIENTVERSION"):
            try:
                workflow["WFWorkflowMinimumClientVersion"] = int(
                    shortcut["ZMINIMUMCLIENTVERSION"]
                )
            except (TypeError, ValueError):
                pass
        return workflow
    finally:
        con.close()


def extract_all_workflows(db_path=None):
    """{name: WFWorkflow dict or None} for every non-tombstoned shortcut.

    None means the shortcut was listed but couldn't be reconstructed (no
    ZACTIONS row, or a decode failure) -- callers should report these, not
    silently skip them.
    """
    db_path = db_path or find_main_store()
    if db_path is None:
        raise FileNotFoundError("No Shortcuts library store found.")
    workflows = {}
    for s in list_shortcuts(db_path=db_path):
        workflows[s["name"]] = extract_workflow(s["name"], db_path=db_path)
    return workflows


RUN_WORKFLOW_IDENTIFIER = "is.workflow.actions.runworkflow"


def find_called_shortcuts(actions):
    """Names of shortcuts invoked by "Run Shortcut" actions within `actions`."""
    called = []
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        if a.get("WFWorkflowActionIdentifier") != RUN_WORKFLOW_IDENTIFIER:
            continue
        params = a.get("WFWorkflowActionParameters") or {}
        name = params.get("WFWorkflowName")
        if not isinstance(name, str):
            wf_ref = params.get("WFWorkflow")
            name = None
            if isinstance(wf_ref, dict):
                candidate = wf_ref.get("workflowName") or wf_ref.get("WFWorkflowName")
                if isinstance(candidate, str):
                    name = candidate
        # A dynamic target (e.g. a variable instead of a literal name) can't
        # be resolved statically -- skip it rather than record a non-string.
        if isinstance(name, str) and name:
            called.append(name)
    return called


def build_call_graph(root_name, db_path=None):
    """Recursively extract `root_name` and every shortcut it calls (directly
    or transitively) via "Run Shortcut" actions.

    Returns {"workflows": {name: WFWorkflow dict or None}, "edges": {name:
    [called names]}, "missing": [names]}. A workflow is None, and its name
    listed in "missing", when it's referenced by a Run Shortcut action but
    not found in the library (deleted, or a sync placeholder).
    """
    db_path = db_path or find_main_store()
    if db_path is None:
        raise FileNotFoundError("No Shortcuts library store found.")

    workflows = {}
    edges = {}
    missing = []
    stack = [root_name]
    while stack:
        name = stack.pop()
        if name in workflows:
            continue
        wf = extract_workflow(name, db_path=db_path)
        workflows[name] = wf
        if wf is None:
            missing.append(name)
            continue
        called = find_called_shortcuts(wf.get("WFWorkflowActions"))
        edges[name] = called
        for c in called:
            if c not in workflows:
                stack.append(c)
    return {"workflows": workflows, "edges": edges, "missing": missing}


def build_full_call_graph(workflows):
    """Edges (via "Run Shortcut" actions) across an already-extracted set of
    workflows, e.g. from extract_all_workflows(). Unlike build_call_graph(),
    this covers every shortcut as a node -- including ones nothing calls and
    ones that call nothing -- not just what's reachable from one root.

    Returns {"edges": {name: [called names]}, "missing": [names referenced
    by a Run Shortcut action but not present in `workflows`]}.
    """
    edges = {}
    missing = set()
    for name, wf in workflows.items():
        if wf is None:
            continue
        called = find_called_shortcuts(wf.get("WFWorkflowActions"))
        edges[name] = called
        for c in called:
            if c not in workflows:
                missing.add(c)
    return {"edges": edges, "missing": sorted(missing)}


_ACTION_LABELS = {
    "runworkflow": "Run Shortcut",
    "runextension": "Share to App",
    "gettext": "Text",
    "setvariable": "Set Variable",
    "getvariable": "Get Variable",
    "conditional": "If/Otherwise/End If",
    "choosefromlist": "Choose from List",
    "repeat.each": "Repeat with Each",
    "repeat.count": "Repeat",
    "comment": "Comment",
    "showresult": "Show Result",
    "openapp": "Open App",
    "properties.articles": "Get Details of Article",
    "getclipboard": "Get Clipboard",
    "setclipboard": "Set Clipboard",
    "downloadurl": "Download URL",
    "getitemname": "Get Item Name",
    "getrichtextfromhtml": "Get Rich Text from HTML",
    "url.expand": "Expand URL",
    "ask": "Ask for Input",
    "postonfacebook": "Post on Facebook",
    "tweet": "Post Tweet",
    "share": "Share",
    "count": "Count",
    "list": "List",
    "number": "Number",
    "exit": "Stop This Shortcut",
    "nothing": "Nothing",
    "alert": "Show Alert",
    "notification": "Show Notification",
    "vibrate": "Vibrate",
    "wait": "Wait",
    "if": "If",
    "repeat": "Repeat",
    "detect.link": "Get URLs from Input",
    "url": "URL",
    "openurl": "Open URLs",
}


def _resolve_text(value):
    """Best-effort plain-text rendering of a WFTextTokenString/Attachment
    value: variable/output references become {Name}, literal strings pass
    through, anything else falls back to a short repr."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return repr(value)[:80]

    def label_of(attachment):
        if not isinstance(attachment, dict):
            return "?"
        if attachment.get("Type") == "Variable":
            return attachment.get("VariableName", "?")
        if "OutputName" in attachment:
            return attachment["OutputName"]
        return attachment.get("Type", "?")

    inner = value.get("Value", value)
    if isinstance(inner, dict) and "string" in inner:
        s = inner["string"]
        attachments = inner.get("attachmentsByRange") or {}
        # Each range key is "{start, length}"; placeholders are U+FFFC.
        by_start = {}
        for key, attachment in attachments.items():
            try:
                start = int(key.strip("{}").split(",")[0].strip())
            except (ValueError, IndexError):
                continue
            by_start[start] = attachment
        out = []
        for i, ch in enumerate(s):
            if ch == "￼" and i in by_start:
                out.append("{" + label_of(by_start[i]) + "}")
            elif ch != "￼":
                out.append(ch)
        return "".join(out)
    if isinstance(inner, dict):
        return "{" + label_of(inner) + "}"
    return repr(inner)[:80]


def describe_action(action, index):
    """One human-readable line for a single WFWorkflowActions entry."""
    ident = action.get("WFWorkflowActionIdentifier", "?")
    params = action.get("WFWorkflowActionParameters") or {}
    short = ident.replace("is.workflow.actions.", "")
    label = _ACTION_LABELS.get(short, short.replace(".", " ").replace("_", " ").title())

    if short == "conditional":
        mode = params.get("WFControlFlowMode")
        if mode == 0:
            cond = params.get("WFConditionalActionString")
            suffix = f": {_resolve_text(cond) if isinstance(cond, dict) else cond!r}" if cond is not None else ""
            return f"{index:>3}. If{suffix}"
        if mode == 1:
            return f"{index:>3}. Otherwise"
        return f"{index:>3}. End If"
    if short == "setvariable":
        return f"{index:>3}. Set Variable '{params.get('WFVariableName')}' = {_resolve_text(params.get('WFInput'))}"
    if short == "getvariable":
        var = (params.get("WFVariable") or {}).get("Value", {})
        return f"{index:>3}. Get Variable '{var.get('VariableName', '?')}'"
    if short == "runworkflow":
        name = params.get("WFWorkflowName") or (params.get("WFWorkflow") or {}).get("workflowName")
        return f"{index:>3}. Run Shortcut: '{name}'"
    if short == "runextension":
        app = (params.get("WFApp") or {}).get("Name") or params.get("WFAppIdentifier")
        return f"{index:>3}. Share to App: '{app}' -- {_resolve_text(params.get('WFInput'))}"
    if short == "openapp":
        app = (params.get("WFSelectedApp") or {}).get("Name") or params.get("WFAppIdentifier")
        return f"{index:>3}. Open App: '{app}'"
    if short == "gettext":
        return f"{index:>3}. Text: {_resolve_text(params.get('WFTextActionText'))}"
    if short == "showresult":
        return f"{index:>3}. Show Result: {_resolve_text(params.get('Text'))}"
    if short == "comment":
        return f"{index:>3}. Comment: {_resolve_text(params.get('WFCommentActionText'))}"
    if short == "choosefromlist":
        prompt = params.get("WFChooseFromListActionPrompt")
        return f"{index:>3}. Choose from List" + (f" ({prompt!r})" if prompt else "")
    if short == "list":
        items = params.get("WFItems")
        if isinstance(items, list) and all(isinstance(i, str) for i in items):
            return f"{index:>3}. List: {items}"
        return f"{index:>3}. List"
    if short == "properties.articles":
        return f"{index:>3}. Get Details of Article: {params.get('WFContentItemPropertyName')}"

    # Generic fallback: show scalar top-level params, resolve text-shaped ones.
    parts = []
    for key, value in params.items():
        if key in ("UUID", "GroupingIdentifier"):
            continue
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}={value!r}")
        elif isinstance(value, dict) and ("Value" in value or "string" in value):
            parts.append(f"{key}={_resolve_text(value)!r}")
    suffix = " (" + ", ".join(parts[:4]) + ")" if parts else ""
    return f"{index:>3}. {label}{suffix}"


def write_action_list(workflow, name, out_path):
    """Human-readable Markdown listing of every action in `workflow`."""
    actions = workflow.get("WFWorkflowActions") or []
    lines = [f"# {name}", "", f"{len(actions)} action(s)", ""]
    for i, a in enumerate(actions):
        lines.append(describe_action(a, i))
    Path(out_path).write_text("\n".join(lines) + "\n")


def _json_default(obj):
    if isinstance(obj, plistlib.UID):
        return {"$uid": obj.data}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)
