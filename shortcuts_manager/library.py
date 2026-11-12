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
            "FROM ZSHORTCUT WHERE ZTOMBSTONED = 0 ORDER BY ZNAME"
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
            "SELECT * FROM ZSHORTCUT WHERE ZNAME = ? AND ZTOMBSTONED = 0 LIMIT 1",
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


def _json_default(obj):
    if isinstance(obj, plistlib.UID):
        return {"$uid": obj.data}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)
