"""CLI for pulling the Shortcuts app's local library out for inspection.

Usage:
    python3 -m shortcuts_manager.cli inspect [--out DIR]
    python3 -m shortcuts_manager.cli dump-raw [--out DIR]
    python3 -m shortcuts_manager.cli list-shortcuts
    python3 -m shortcuts_manager.cli extract-one --name NAME [--out DIR]

Requires Full Disk Access for whatever process runs python3 here -- the
Shortcuts Group Containers are TCC-protected. Read-only: see library.py.
"""

import argparse
import json
import sys
from pathlib import Path

from . import library, workflow

DEFAULT_OUT = Path("<PROJECTS_DIR>/ShortcutsExtracted")


def cmd_inspect(args):
    stores = library.find_stores()
    if not stores:
        print(
            "No Shortcuts stores found or not readable. "
            "Grant this process Full Disk Access in "
            "System Settings -> Privacy & Security -> Full Disk Access.",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out) / "schema"
    out_dir.mkdir(parents=True, exist_ok=True)

    for db_path in stores:
        print(f"\n=== {db_path} ===")
        schema = library.inspect_schema(db_path)
        for table, info in schema.items():
            cols = ", ".join(c["name"] for c in info["columns"])
            print(f"  {table} ({info['row_count']} rows): {cols}")
        (out_dir / f"{db_path.stem}.json").write_text(json.dumps(schema, indent=2))

    print(f"\nSchema summaries written to {out_dir}")
    return 0


def cmd_dump_raw(args):
    stores = library.find_stores()
    if not stores:
        print(
            "No Shortcuts stores found or not readable. "
            "Grant this process Full Disk Access in "
            "System Settings -> Privacy & Security -> Full Disk Access.",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out) / "raw"
    for db_path in stores:
        written = library.dump_raw(db_path, out_dir)
        print(f"{db_path} -> {written}")
    return 0


def cmd_list_shortcuts(args):
    try:
        shortcuts = library.list_shortcuts()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    for s in shortcuts:
        print(f"{s['name']}  ({s['action_count']} actions, {s['subtitle']})")
    return 0


def cmd_extract_one(args):
    try:
        wf = library.extract_workflow(args.name)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    if wf is None:
        print(f"No shortcut named {args.name!r} found.", file=sys.stderr)
        return 1

    out_dir = Path(args.out) / "unsigned"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.name}.shortcut"
    workflow.write_unsigned(wf, out_path)
    print(f"Wrote unsigned, editable plist: {out_path}")
    print("Edit its WFWorkflowActions, then sign it with:")
    print(f'  shortcuts sign -m anyone -i "{out_path}" -o "{args.name}.shortcut"')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="shortcuts_manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="List tables/columns/row counts.")
    p_inspect.add_argument("--out", default=str(DEFAULT_OUT))
    p_inspect.set_defaults(func=cmd_inspect)

    p_dump = sub.add_parser("dump-raw", help="Dump every table's rows to JSON.")
    p_dump.add_argument("--out", default=str(DEFAULT_OUT))
    p_dump.set_defaults(func=cmd_dump_raw)

    p_list = sub.add_parser("list-shortcuts", help="List every shortcut by name.")
    p_list.set_defaults(func=cmd_list_shortcuts)

    p_extract = sub.add_parser(
        "extract-one", help="Reconstruct one shortcut as an editable unsigned plist."
    )
    p_extract.add_argument("--name", required=True)
    p_extract.add_argument("--out", default=str(DEFAULT_OUT))
    p_extract.set_defaults(func=cmd_extract_one)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
