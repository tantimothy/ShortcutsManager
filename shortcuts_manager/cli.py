"""CLI for pulling the Shortcuts app's local library out for inspection.

Usage:
    python3 -m shortcuts_manager.cli inspect [--out DIR]
    python3 -m shortcuts_manager.cli dump-raw [--out DIR]
    python3 -m shortcuts_manager.cli list-shortcuts
    python3 -m shortcuts_manager.cli extract-one --name NAME [--out DIR]
    python3 -m shortcuts_manager.cli map-calls --name NAME [--out DIR]

Requires Full Disk Access for whatever process runs python3 here -- the
Shortcuts Group Containers are TCC-protected. Read-only: see library.py.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import library, workflow

_UNSAFE_FILENAME_CHARS = '/\\:*?"<>|'


def _safe_filename(name):
    return "".join("-" if c in _UNSAFE_FILENAME_CHARS else c for c in name)

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


def cmd_map_calls(args):
    try:
        graph = library.build_call_graph(args.name)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    out_dir = Path(args.out) / "unsigned"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, wf in graph["workflows"].items():
        if wf is not None:
            workflow.write_unsigned(wf, out_dir / f"{name}.shortcut")

    graph_path = Path(args.out) / "call_graph.json"
    graph_path.write_text(
        json.dumps(
            {"root": args.name, "edges": graph["edges"], "missing": graph["missing"]},
            indent=2,
        )
    )

    print(f"Mapped {len(graph['workflows'])} shortcut(s) reachable from {args.name!r}.")
    for name, called in graph["edges"].items():
        if called:
            print(f"  {name} -> {', '.join(called)}")
    print(f"\nCall graph written to {graph_path}")
    print(f"Unsigned plists written to {out_dir}")
    if graph["missing"]:
        print(
            f"Referenced but not found in the library: {', '.join(graph['missing'])}",
            file=sys.stderr,
        )
    return 0


def cmd_extract_all(args):
    try:
        workflows = library.extract_all_workflows()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    out = Path(args.out)
    unsigned_dir = out / "unsigned"
    signed_dir = out / "signed"
    actions_dir = out / "inventory" / "actions"
    for d in (unsigned_dir, signed_dir, actions_dir):
        d.mkdir(parents=True, exist_ok=True)

    failed = []
    empty = []
    sign_failed = []
    total = len(workflows)
    for i, (name, wf) in enumerate(workflows.items(), start=1):
        print(f"[{i}/{total}] {name}", flush=True)
        safe = _safe_filename(name)
        if wf is None:
            failed.append(name)
            continue
        unsigned_path = unsigned_dir / f"{safe}.shortcut"
        workflow.write_unsigned(wf, unsigned_path)
        library.write_action_list(wf, name, actions_dir / f"{safe}.md")
        # The DB's cached ZACTIONCOUNT is unreliable (confirmed stale on
        # live shortcuts) -- only the actually-decoded action list counts.
        if len(wf.get("WFWorkflowActions") or []) == 0:
            empty.append(name)
            continue
        try:
            workflow.sign(unsigned_path, signed_dir / f"{safe}.shortcut", mode="anyone")
        except subprocess.CalledProcessError:
            sign_failed.append(name)

    graph_workflows = {
        n: w for n, w in workflows.items() if w is not None and w.get("WFWorkflowActions")
    }
    graph = library.build_full_call_graph(graph_workflows)
    lines = ["# Shortcut call graph", "", "```mermaid", "graph LR"]
    ids = {name: f"n{i}" for i, name in enumerate(graph_workflows)}
    for name, node_id in ids.items():
        label = name.replace('"', "'")
        lines.append(f'  {node_id}["{label}"]')
    missing_ids = {}
    for caller, callees in graph["edges"].items():
        for callee in callees:
            if callee in ids:
                lines.append(f"  {ids[caller]} --> {ids[callee]}")
            else:
                if callee not in missing_ids:
                    missing_id = f"missing{len(missing_ids)}"
                    missing_ids[callee] = missing_id
                    label = callee.replace('"', "'")
                    lines.append(f'  {missing_id}["{label} (missing)"]:::missing')
                lines.append(f"  {ids[caller]} --> {missing_ids[callee]}")
    lines.append("  classDef missing stroke-dasharray: 5 5")
    lines.append("```")
    (out / "inventory" / "call_graph.md").write_text("\n".join(lines) + "\n")

    print(f"Extracted {len(workflows)} shortcut(s).")
    print(f"Unsigned plists: {unsigned_dir}")
    print(f"Signed, re-importable binaries: {signed_dir}")
    print(f"Human-readable action lists: {actions_dir}")
    print(f"Call graph: {out / 'inventory' / 'call_graph.md'}")
    if failed:
        print(f"Could not reconstruct ({len(failed)}): {', '.join(failed)}", file=sys.stderr)
    if empty:
        print(
            f"Genuinely 0 actions, not signed ({len(empty)}): {', '.join(empty)}",
            file=sys.stderr,
        )
    if sign_failed:
        print(f"Signing failed ({len(sign_failed)}): {', '.join(sign_failed)}", file=sys.stderr)
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

    p_map = sub.add_parser(
        "map-calls",
        help="Recursively map a shortcut and everything it calls via Run Shortcut actions.",
    )
    p_map.add_argument("--name", required=True)
    p_map.add_argument("--out", default=str(DEFAULT_OUT))
    p_map.set_defaults(func=cmd_map_calls)

    p_all = sub.add_parser(
        "extract-all",
        help="Extract every shortcut: unsigned plist, signed binary, human-readable "
        "action list, and a full call graph.",
    )
    p_all.add_argument("--out", default=str(DEFAULT_OUT))
    p_all.set_defaults(func=cmd_extract_all)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
