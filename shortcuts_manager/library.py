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
import subprocess
from collections import deque
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


_TRIGGER_DESCRIPTIONS = {
    "WFPlugInTrigger": lambda p: f"Charger {p.get('WFConnectionType', '?')}ed",
    "WFBatteryLevelTrigger": lambda p: (
        f"Battery level {p.get('WFBatteryLevelComparison', '?').replace('_', ' ')} "
        f"{p.get('WFBatteryLevel', '?')}%"
    ),
    "WFAirplaneModeTrigger": lambda p: f"Airplane Mode turned {p.get('WFAirplaneModeType', '?')}",
    "WFLeaveLocationTrigger": lambda p: (
        f"Leaving {(p.get('WFLeaveLocation') or {}).get('locationName', '?')}"
    ),
    "WFArriveLocationTrigger": lambda p: (
        f"Arriving at {(p.get('WFArriveLocation') or {}).get('locationName', '?')}"
    ),
}


def describe_trigger(identifier, parameters):
    """Best-effort human-readable summary of one automation trigger.
    `WFArriveLocationTrigger`'s shape is a guess by symmetry with
    `WFLeaveLocationTrigger` (the only location trigger type actually seen
    in this library's data is "leave") -- confirm it if one ever shows up.
    Falls back to raw identifier+parameters for any other type, same as
    describe_action()'s generic fallback, so nothing is silently dropped."""
    fn = _TRIGGER_DESCRIPTIONS.get(identifier)
    if fn:
        try:
            return fn(parameters or {})
        except Exception:
            pass
    return f"{identifier} {parameters!r}"


def extract_automations(db_path=None):
    """Personal Automations: each is a `ZUNIFIEDTRIGGER` row (the trigger
    condition) joined to the `ZSHORTCUT` it runs when that condition fires.

    Not reachable via Shortcuts.app's own AppleScript dictionary -- `sdef`
    shows no "automation" class there, only `shortcut` and `folder` (see
    `export_folder_hierarchy()`) -- so this reads straight from the SQLite
    store instead, same as everything else in this module except folders.
    Unlike the folder hierarchy, the trigger condition itself
    (`WFTriggerSerializedParameters`) decodes as a plain plist with no
    archiver or CRDT wrapping -- `_decode_value()` already handles it.

    Returns a list of {"shortcut_name", "trigger_identifier", "trigger_uuid",
    "parameters", "description"}, ordered by shortcut name."""
    db_path = db_path or find_main_store()
    if db_path is None:
        raise FileNotFoundError("No Shortcuts library store found.")
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT t.ZUUID, t.ZDATA, s.ZNAME "
            "FROM ZUNIFIEDTRIGGER t JOIN ZSHORTCUT s ON t.ZSHORTCUT = s.Z_PK "
            "WHERE s.ZTOMBSTONED = 0 AND s.ZCONFLICTOF IS NULL "
            "ORDER BY s.ZNAME"
        ).fetchall()
        out = []
        for uuid, data, name in rows:
            decoded = _decode_value(data) if isinstance(data, bytes) else (data or {})
            identifier = decoded.get("WFTriggerIdentifier", "?")
            params = decoded.get("WFTriggerSerializedParameters") or {}
            out.append(
                {
                    "shortcut_name": name,
                    "trigger_identifier": identifier,
                    "trigger_uuid": uuid,
                    "parameters": params,
                    "description": describe_trigger(identifier, params),
                }
            )
        return out
    finally:
        con.close()


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


def _topo_order(nodes, edges):
    """Rough BFS order from root members (nothing in `nodes` calls them)
    so Mermaid's layout trends top-left -> bottom-right within a cluster."""
    incoming = {n: 0 for n in nodes}
    for n in nodes:
        for c in edges.get(n, []):
            if c in incoming:
                incoming[c] += 1
    order = []
    visited = set()
    queue = deque(sorted(n for n in nodes if incoming[n] == 0))
    while queue:
        n = queue.popleft()
        if n in visited:
            continue
        visited.add(n)
        order.append(n)
        for c in edges.get(n, []):
            if c in nodes and c not in visited:
                queue.append(c)
    for n in sorted(nodes):  # leftover cycle members not reached above
        if n not in visited:
            order.append(n)
            visited.add(n)
    return order


def _render_mermaid_cluster(order, edges, truly_missing):
    """`truly_missing` is the library-wide set of names that don't exist
    anywhere (real dangling references) -- a callee that's merely outside
    this particular slice (e.g. a hub's neighbor that itself calls
    something two hops away) is real and just silently dropped, not drawn
    as a fake "(missing)" node."""
    lines = ["```mermaid", "graph LR"]
    ids = {name: f"n{i}" for i, name in enumerate(order)}
    for name, node_id in ids.items():
        lines.append(f'  {node_id}["{name.replace(chr(34), chr(39))}"]')
    missing_ids = {}
    for caller in order:
        for callee in edges.get(caller, []):
            if callee in ids:
                lines.append(f"  {ids[caller]} --> {ids[callee]}")
            elif callee in truly_missing:
                if callee not in missing_ids:
                    missing_ids[callee] = f"missing{len(missing_ids)}"
                    label = callee.replace('"', "'")
                    lines.append(f'  {missing_ids[callee]}["{label} (missing)"]:::missing')
                lines.append(f"  {ids[caller]} --> {missing_ids[callee]}")
            # else: real shortcut, just outside this slice -- omit the edge.
    lines.append("  classDef missing stroke-dasharray: 5 5")
    lines.append("```")
    return "\n".join(lines)


def render_mermaid_call_graph(graph, max_cluster_size=12):
    """One Mermaid diagram (left-to-right, `graph LR`) per weakly-connected
    cluster of callers/callees, instead of one diagram for the whole
    library -- a single graph mixing every hub (Post Pic, Share to Social
    Media, the Glympse family, the Battery/Charger/Low Power family, ...)
    forces a very wide, squashed layout that's unreadable regardless of
    direction. Isolated shortcuts (no calls in or out) are left out of
    every diagram entirely.

    A cluster larger than `max_cluster_size` is also split further: its
    "hub" nodes (out-degree + in-degree >= 3 within the cluster) each get
    their own small diagram of just themselves and their direct neighbors,
    since a hub-and-spoke cluster is still unreadable as one block even
    though it's technically one connected component.

    Returns [(title, mermaid_markdown), ...], isolated_names, overview --
    overview is [(representative_names, size), ...] for every real
    weakly-connected component (largest first), *before* any hub
    splitting -- the true network size, for spotting which shortcuts have
    a sprawling call web at a glance, independent of how many diagram
    sections that web got split into.
    """
    edges = graph["edges"]
    truly_missing = set(graph["missing"])
    callees = {c for called in edges.values() for c in called}
    connected = {n for n, called in edges.items() if called} | (callees & edges.keys())
    isolated = sorted(n for n in edges if n not in connected)

    # Undirected adjacency for clustering (a caller and its callee belong
    # to the same cluster regardless of edge direction).
    undirected = {n: set() for n in connected}
    for caller, called in edges.items():
        if caller not in connected:
            continue
        for callee in called:
            if callee in connected:
                undirected[caller].add(callee)
                undirected[callee].add(caller)

    clusters = []
    seen = set()
    for start in sorted(connected):
        if start in seen:
            continue
        component = set()
        queue = deque([start])
        while queue:
            n = queue.popleft()
            if n in component:
                continue
            component.add(n)
            queue.extend(undirected[n] - component)
        seen |= component
        clusters.append(component)
    clusters.sort(key=len, reverse=True)
    overview = [(_topo_order(cluster, edges)[:5], len(cluster)) for cluster in clusters]

    sections = []
    for cluster in clusters:
        if len(cluster) <= max_cluster_size:
            order = _topo_order(cluster, edges)
            title = ", ".join(order[:4]) + (", ..." if len(order) > 4 else "")
            sections.append((f"{title} ({len(cluster)})", _render_mermaid_cluster(order, edges, truly_missing)))
            continue
        degree = {n: len(undirected[n]) for n in cluster}
        hubs = sorted((n for n in cluster if degree[n] >= 3), key=lambda n: -degree[n])
        covered = set()
        for hub in hubs:
            neighborhood = {hub} | undirected[hub]
            if neighborhood <= covered:
                continue
            covered |= neighborhood
            order = _topo_order(neighborhood, edges)
            sections.append((f"{hub} and its direct calls ({len(order)})", _render_mermaid_cluster(order, edges, truly_missing)))
        leftover = cluster - covered
        if leftover:
            order = _topo_order(leftover, edges)
            title = ", ".join(order[:4]) + (", ..." if len(order) > 4 else "")
            sections.append((f"{title} ({len(leftover)})", _render_mermaid_cluster(order, edges, truly_missing)))

    return sections, isolated, overview


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
    if isinstance(inner, dict) and "WFDictionaryFieldValueItems" in inner:
        entries = inner["WFDictionaryFieldValueItems"] or []
        pairs = [f"{_resolve_text(it.get('WFKey'))}: {_resolve_text(it.get('WFValue'))}" for it in entries]
        return "{" + ", ".join(pairs) + "}"
    if isinstance(inner, dict) and "Value" in inner and "Type" not in inner:
        # Another layer of wrapping (e.g. a dictionary/form field's value
        # carries its own WFTokenAttachmentParameterState-wrapped token
        # rather than the plain WFTextTokenString/Attachment shape) --
        # unwrap it the same way instead of giving up on it.
        return _resolve_text(inner)
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


_REPEAT_IDENTIFIERS = {"repeat.count", "repeat.each"}


_BRANCHING_IDENTIFIERS = {"conditional", "choosefrommenu"}


def _implicit_input_text(actions, prev_index):
    """Label for an input the action at (conceptually) `prev_index + 1` left
    unwired. Shortcuts.app doesn't leave this blank at runtime -- it
    implicitly pipes in the shortcut's own input (if there's no preceding
    action) or the immediately preceding action's result. Rendering
    nothing here (the old behavior) reads as a wiring gap; render what
    actually feeds in.

    Most control-flow markers don't themselves produce a value to pipe
    forward, so walk back past them -- with two exceptions:
    - Repeat with Each's own start marker: its implicit value genuinely is
      the loop's `Repeat Item`.
    - A branch marker (Otherwise/Case 'X') or an End If/End Choose from
      Menu: walking back one step from these lands on a *different*,
      mutually-exclusive branch's last action (the one physically
      preceding it in the flat array) -- not "whatever ran before this
      branch", which is the wrong predecessor, and not necessarily "what
      actually ran" either, since only one branch out of several executes.
      Rather than confidently naming the wrong branch, say plainly that it
      depends on which branch ran.

    `actions` and `prev_index` must refer to the same flat
    WFWorkflowActions list/index this call chain started from, so a
    chain of several consecutive unwired actions resolves correctly
    instead of each link re-deriving its own predecessor from scratch."""
    if actions is None or prev_index is None:
        return "{ExtensionInput}"
    idx = prev_index
    while idx >= 0:
        prev = actions[idx]
        prev_params = prev.get("WFWorkflowActionParameters") or {}
        prev_short = prev.get("WFWorkflowActionIdentifier", "").replace("is.workflow.actions.", "")
        prev_mode = prev_params.get("WFControlFlowMode")
        if prev_short == "repeat.each" and prev_mode == 0:
            return "{Repeat Item}"
        if prev_short in _BRANCHING_IDENTIFIERS and prev_mode in (1, 2):
            return "{implicit input -- depends which branch ran, can't resolve statically}"
        if prev_short in _REPEAT_IDENTIFIERS or (prev_short in _BRANCHING_IDENTIFIERS and prev_mode == 0):
            idx -= 1
            continue
        return f"{{implicit input from previous action: {describe_action(prev, actions, idx)}}}"
    return "{ExtensionInput}"


def describe_action(action, actions=None, index=None):
    """One human-readable pseudocode line for a single WFWorkflowActions
    entry, with no leading index -- the caller handles indentation for
    control-flow blocks (If/Otherwise/End If, Repeat/End Repeat).

    `actions`/`index` are the flat WFWorkflowActions list this action came
    from and its index in it (both None if not available) -- used only to
    describe an input this action left unwired; see
    `_implicit_input_text`."""
    ident = action.get("WFWorkflowActionIdentifier", "?")
    params = action.get("WFWorkflowActionParameters") or {}
    short = ident.replace("is.workflow.actions.", "")
    label = _ACTION_LABELS.get(short, short.replace(".", " ").replace("_", " ").title())
    mode = params.get("WFControlFlowMode")
    prev_index = (index - 1) if index is not None else None

    if short == "conditional":
        if mode == 0:
            cond = params.get("WFConditionalActionString")
            suffix = f" {_resolve_text(cond) if isinstance(cond, dict) else cond!r}" if cond is not None else ""
            return f"If{suffix}:"
        if mode == 1:
            return "Otherwise:"
        return "End If"
    if short in _REPEAT_IDENTIFIERS:
        if mode == 0:
            if short == "repeat.count":
                times = params.get("WFRepeatCount")
                times_text = _resolve_text(times) if isinstance(times, dict) else times
                return f"Repeat {times_text} times:"
            wf_input = params.get("WFInput")
            input_text = _resolve_text(wf_input) if wf_input is not None else _implicit_input_text(actions, prev_index)
            return f"Repeat with each item in {input_text}:"
        return "End Repeat"
    if short == "choosefrommenu":
        if mode == 0:
            prompt = params.get("WFMenuPrompt")
            suffix = f" {_resolve_text(prompt) if isinstance(prompt, dict) else prompt!r}" if prompt else ""
            return f"Choose from Menu{suffix}:"
        if mode == 1:
            return f"Case {params.get('WFMenuItemTitle')!r}:"
        return "End Choose from Menu"
    if short == "setvariable":
        wf_input = params.get("WFInput")
        input_text = _resolve_text(wf_input) if wf_input is not None else _implicit_input_text(actions, prev_index)
        return f"Set Variable '{params.get('WFVariableName')}' = {input_text}"
    if short == "getvariable":
        var = (params.get("WFVariable") or {}).get("Value", {})
        return f"Get Variable '{var.get('VariableName', '?')}'"
    if short == "runworkflow":
        name = params.get("WFWorkflowName") or (params.get("WFWorkflow") or {}).get("workflowName")
        return f"Run Shortcut: '{name}'"
    if short == "runextension":
        app = (params.get("WFApp") or {}).get("Name") or params.get("WFAppIdentifier")
        return f"Share to App: '{app}' -- {_resolve_text(params.get('WFInput'))}"
    if short == "openapp":
        app = (params.get("WFSelectedApp") or {}).get("Name") or params.get("WFAppIdentifier")
        return f"Open App: '{app}'"
    if short == "gettext":
        return f"Text: {_resolve_text(params.get('WFTextActionText'))}"
    if short == "showresult":
        return f"Show Result: {_resolve_text(params.get('Text'))}"
    if short == "comment":
        return f"Comment: {_resolve_text(params.get('WFCommentActionText'))}"
    if short == "dictionary":
        custom_name = params.get("CustomOutputName")
        suffix = f" (as '{custom_name}')" if custom_name else ""
        return f"Dictionary{suffix}: {_resolve_text(params.get('WFItems'))}"
    if short == "choosefromlist":
        prompt = params.get("WFChooseFromListActionPrompt")
        if prompt:
            text = _resolve_text(prompt) if isinstance(prompt, dict) else prompt
            return f"Choose from List ({text!r})"
        return "Choose from List"
    if short == "list":
        items = params.get("WFItems")
        if isinstance(items, list) and all(isinstance(i, str) for i in items):
            return f"List: {items}"
        return "List"
    if short == "properties.articles":
        return f"Get Details of Article: {params.get('WFContentItemPropertyName')}"

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
    return f"{label}{suffix}"


def write_action_list(workflow, name, out_path, folder=None, automation_trigger=None):
    """Human-readable, indented pseudocode listing of every action in
    `workflow` -- If/Otherwise/End If and Repeat/End Repeat blocks are
    nested, matching the shortcut's actual control flow.

    Wrapped in a fenced code block: plain consecutive Markdown lines (no
    blank line between them) get collapsed into one run-on paragraph by
    any renderer, silently dropping both the line breaks and the
    indentation -- a code fence is what keeps this readable as pseudocode.

    `folder` (from export_folder_hierarchy()) and `automation_trigger`
    (a description string from extract_automations(), for a shortcut
    that's also a Personal Automation) are optional context lines from
    two completely different data sources than this function's own --
    see cmd_extract_all(), which is what actually joins them in. Left out
    of the header entirely when None/not provided, rather than printing
    a bare "(none)", since most shortcuts have neither."""
    actions = workflow.get("WFWorkflowActions") or []
    lines = [f"# {name}", "", f"{len(actions)} action(s)"]
    if folder:
        lines.append(f"Folder: {folder}")
    if automation_trigger:
        lines.append(f"Automation trigger: {automation_trigger}")
    lines += ["", "```"]
    depth = 0
    indent = "    "
    for i, a in enumerate(actions):
        params = a.get("WFWorkflowActionParameters") or {}
        mode = params.get("WFControlFlowMode")
        if mode in (1, 2):
            depth = max(depth - 1, 0)
        lines.append(indent * depth + describe_action(a, actions, i))
        if mode in (0, 1):
            depth += 1
    lines.append("```")
    Path(out_path).write_text("\n".join(lines) + "\n")


def _json_default(obj):
    if isinstance(obj, plistlib.UID):
        return {"$uid": obj.data}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)


_FOLDER_APPLESCRIPT = """
tell application "Shortcuts Events"
    set folderLines to ""
    repeat with f in folders
        set folderLines to folderLines & (name of f) & "\t" & (id of f) & linefeed
    end repeat
    set shortcutLines to ""
    repeat with s in shortcuts
        try
            set fname to name of folder of s
        on error
            set fname to ""
        end try
        set shortcutLines to shortcutLines & (name of s) & "\t" & fname & linefeed
    end repeat
    return folderLines & "===SPLIT===" & shortcutLines
end tell
"""


def export_folder_hierarchy(timeout=120):
    """Folder membership via Shortcuts.app's own AppleScript dictionary
    ("Shortcuts Events") -- not from the SQLite store at all.

    Folder/shortcut organization isn't reachable through anything
    find_stores()/dump_raw() exposes: ZCOLLECTION (the obvious Core-Data-
    naming candidate) holds only Apple's own internal "QuickActions" row,
    confirmed empty of user folders on two separate fresh dumps, and no
    other table references one. It turns out to actually live in
    ZLIBRARY.ZDATA, as a custom "crdt"-magic-prefixed, protobuf-shaped
    document with its own string-interning pool -- undocumented anywhere
    publicly, and reverse-engineering its exact tree topology turned out to
    be unnecessary work: Shortcuts.app exposes the same information
    directly and reliably through its own public scripting dictionary
    (`sdef /System/Applications/Shortcuts.app` -- every `shortcut` has a
    `folder` property), which is what this function actually uses.

    This needs the Automation permission for whatever process runs this to
    control "Shortcuts Events" (a one-time system permission prompt), not
    Full Disk Access -- a different gate than everything else in this
    module. Before that permission is granted, even the simplest possible
    AppleScript call (e.g. `count shortcuts`) hangs indefinitely rather
    than failing outright, which is why this has an explicit timeout
    (raises `subprocess.TimeoutExpired` instead of hanging the caller).

    Returns {"folders": [{"name": ..., "id": ...}, ...],
             "shortcuts": {shortcut_name: folder_name_or_None, ...}}.
    """
    result = subprocess.run(
        ["osascript", "-e", _FOLDER_APPLESCRIPT],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    folder_part, _, shortcut_part = result.stdout.partition("===SPLIT===")
    folders = []
    for line in folder_part.splitlines():
        if not line:
            continue
        name, _, fid = line.partition("\t")
        folders.append({"name": name, "id": fid})
    shortcuts = {}
    for line in shortcut_part.splitlines():
        if not line:
            continue
        name, _, fname = line.partition("\t")
        shortcuts[name] = fname or None
    return {"folders": folders, "shortcuts": shortcuts}
