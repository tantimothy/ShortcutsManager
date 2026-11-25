"""Finds where Shortcuts.app folder names actually live in the local SQLite
store(s), since ZCOLLECTION (the obvious Core-Data-naming candidate) turned
out to hold only Apple's own internal "QuickActions" row, not any of the
folders visibly present in the app's sidebar.

Scans every table/row/column across every store find_stores() locates:
- TEXT/VARCHAR columns: direct substring search.
- BLOB columns: tries nsarchive.loads() (NSKeyedArchiver) first, then plain
  plistlib.loads(), then walks the decoded structure recursively looking for
  the search terms inside nested strings/dict values/list items. A folder
  name could be buried a few levels deep in an archived CloudKit record the
  same way "QuickActions" wasn't itself inside a top-level blob -- found in
  ZIDENTIFIER, a plain column -- so this checks both plain columns and
  inside every decodable blob.

Run (needs Full Disk Access, same as extract.sh/dump-raw):
    python3 examples/find_folder_storage.py

Where this led: folder names (and the string "Post" that happened to look
like a valid nested protobuf message and got misclassified here -- the
real bug this raw-bytes fallback was added to work around) turned out to
be in ZLIBRARY.ZDATA, encoded as a custom "crdt"-magic-prefixed protobuf-
shaped document with its own string-interning pool -- confirmed, but
reverse-engineering that format's exact tree topology (to get real
per-folder membership, not just the flat list of folder names this script
finds) turned out to be unnecessary. Shortcuts.app exposes the same
information directly and reliably through its own AppleScript dictionary
instead -- see `export_folder_hierarchy()` in `shortcuts_manager/library.py`
and `python3 -m shortcuts_manager.cli folders`. Kept here as the record of
what was actually tried and why it was a dead end, same as
`fix_dedup_list.py`.
"""

import json
import plistlib
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import library, nsarchive

CONTAINER_DIRS = [
    Path.home() / "Library/Containers/com.apple.shortcuts/Data/Library/Preferences",
    Path.home() / "Library/Containers/com.apple.shortcuts/Data/Library/Application Support",
    Path.home() / "Library/Containers/com.apple.shortcuts/Data/Library/Caches/com.apple.shortcuts",
    Path.home() / "Library/Containers/com.apple.shortcuts/Data/CloudKit",
]
MAX_FILE_BYTES = 100 * 1024 * 1024  # skip anything bigger -- not where small config/record data would live

SEARCH_TERMS = [
    "Matthew",
    "Glympse/Waze",
    "Nav sub-functions",
    "Post Pic dev",
    "Starter Shortcuts",
    "Pixelmater Pro",
]

OUT_PATH = Path(__file__).resolve().parent / "find_folder_storage_results.json"


def walk_for_match(value, path, terms, hits, depth=0):
    if depth > 12:
        return
    if isinstance(value, str):
        for t in terms:
            if t.lower() in value.lower():
                hits.append({"path": path, "term": t, "value": value})
        return
    if isinstance(value, dict):
        for k, v in value.items():
            walk_for_match(v, f"{path}.{k!r}", terms, hits, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            walk_for_match(v, f"{path}[{i}]", terms, hits, depth + 1)
        return


def decode_blob(data):
    try:
        return nsarchive.loads(data), "nskeyedarchiver"
    except Exception:
        pass
    try:
        return plistlib.loads(data), "plist"
    except Exception:
        pass
    return None, None


def raw_bytes_matches(data, terms):
    """Fallback for when decode_blob() can't structurally parse a blob
    (silently skipped before, hiding whatever's in there): search the raw
    bytes directly as permissively-decoded text, and also try zlib/gzip
    decompression first in case the blob is compressed (latin-1 never
    raises, so this always finds a literal ASCII/UTF-8 substring if one is
    physically present in the bytes, decompressed or not)."""
    hits = []
    candidates = [data]
    try:
        candidates.append(zlib.decompress(data))
    except Exception:
        pass
    try:
        candidates.append(zlib.decompress(data, 16 + zlib.MAX_WBITS))  # gzip
    except Exception:
        pass
    for buf in candidates:
        text = buf.decode("latin-1")
        for t in terms:
            if t.lower() in text.lower():
                i = text.lower().index(t.lower())
                hits.append({"term": t, "context": text[max(0, i - 40):i + len(t) + 40]})
    return hits


def scan_container_files(results):
    """Beyond the Core Data stores find_stores() knows about: raw-byte-scan
    every file under the Shortcuts.app sandbox container's likely config/
    record directories (preferences, app support, caches, CloudKit's local
    record cache) for the search terms, whatever the file format turns out
    to be. This is where folder data might live if it isn't in Core Data at
    all -- a plist, a separate SQLite file dump_raw()/find_stores() never
    looked at, or a raw CloudKit record cache file."""
    for base in CONTAINER_DIRS:
        if not base.exists():
            results.append({"container_path": str(base), "error": "does not exist"})
            continue
        try:
            paths = list(base.rglob("*"))
        except Exception as e:
            results.append({"container_path": str(base), "error": f"rglob failed: {e}"})
            continue
        for p in paths:
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
                if size == 0 or size > MAX_FILE_BYTES:
                    continue
                data = p.read_bytes()
            except Exception as e:
                results.append({"file": str(p), "error": str(e)})
                continue
            for h in raw_bytes_matches(data, SEARCH_TERMS):
                results.append({"file": str(p), "kind": "file:raw-bytes", "term": h["term"], "value": h["context"]})


def main():
    stores = library.find_stores()
    print(f"Found {len(stores)} store file(s):")
    for s in stores:
        print(" -", s)

    results = []
    for store in stores:
        try:
            schema = library.inspect_schema(store)
        except Exception as e:
            results.append({"store": str(store), "error": f"inspect_schema failed: {e}"})
            continue
        con = None
        try:
            con = library._connect(store)
            cur = con.cursor()
            for table in schema:
                col_names = [c["name"] for c in schema[table]["columns"]]
                try:
                    rows = cur.execute(f"SELECT * FROM '{table}'").fetchall()
                except Exception as e:
                    results.append({"store": str(store), "table": table, "error": str(e)})
                    continue
                for row_i, row in enumerate(rows):
                    record = dict(zip(col_names, row))
                    for col, value in record.items():
                        if isinstance(value, str):
                            for t in SEARCH_TERMS:
                                if t.lower() in value.lower():
                                    results.append(
                                        {"store": str(store), "table": table, "row": row_i, "column": col,
                                         "kind": "text", "term": t, "value": value}
                                    )
                        elif isinstance(value, (bytes, bytearray)):
                            raw = bytes(value)
                            decoded, fmt = decode_blob(raw)
                            if decoded is not None:
                                hits = []
                                walk_for_match(decoded, "$", SEARCH_TERMS, hits)
                                for h in hits:
                                    results.append(
                                        {"store": str(store), "table": table, "row": row_i, "column": col,
                                         "kind": f"blob:{fmt}", "term": h["term"], "path": h["path"],
                                         "value": h["value"][:200]}
                                    )
                            # Always also try a raw-bytes scan -- decode_blob()
                            # silently gives up on formats it can't parse
                            # (e.g. a raw/compressed CKRecord encoding that
                            # isn't NSKeyedArchiver or a plain plist), which
                            # would otherwise hide a match with no error.
                            for h in raw_bytes_matches(raw, SEARCH_TERMS):
                                results.append(
                                    {"store": str(store), "table": table, "row": row_i, "column": col,
                                     "kind": "blob:raw-bytes", "term": h["term"], "value": h["context"]}
                                )
        except Exception as e:
            results.append({"store": str(store), "error": f"connect/scan failed: {e}"})
        finally:
            if con is not None:
                con.close()

    print("Scanning container files (preferences, app support, caches, CloudKit cache)...")
    scan_container_files(results)

    OUT_PATH.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n{len(results)} match(es)/error(s). Written to {OUT_PATH}")
    for r in results[:20]:
        print(" -", {k: v for k, v in r.items() if k != "value"}, "->", str(r.get("value"))[:80])


if __name__ == "__main__":
    main()
