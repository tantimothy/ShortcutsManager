"""Read-only access to the Shortcuts app's local Core Data/SQLite library.

This never writes to the store -- it's undocumented, versioned per-OS, and
tied into CloudKit sync state (see README.md). Requires Full Disk Access
for whatever process runs this (Group Containers are TCC-protected).
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


def find_stores():
    """Every *.sqlite file under the Shortcuts Group Containers."""
    home = Path.home()
    stores = []
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


def _json_default(obj):
    if isinstance(obj, plistlib.UID):
        return {"$uid": obj.data}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)
