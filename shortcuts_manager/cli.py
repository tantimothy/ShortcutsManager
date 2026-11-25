"""CLI for pulling the Shortcuts app's local library out for inspection.

Usage:
    python3 -m shortcuts_manager.cli inspect [--out DIR]
    python3 -m shortcuts_manager.cli dump-raw [--out DIR]
    python3 -m shortcuts_manager.cli list-shortcuts
    python3 -m shortcuts_manager.cli extract-one --name NAME [--out DIR]
    python3 -m shortcuts_manager.cli map-calls --name NAME [--out DIR]
    python3 -m shortcuts_manager.cli folders [--out DIR]
    python3 -m shortcuts_manager.cli automations [--out DIR]

Requires Full Disk Access for whatever process runs python3 here -- the
Shortcuts Group Containers are TCC-protected. Read-only: see library.py.

`folders` is the one exception: it doesn't touch the SQLite store at all
(folder/group data isn't reachable there), so it needs the Automation
permission for this process to control Shortcuts.app instead of Full Disk
Access -- see `export_folder_hierarchy()` in library.py.
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

DEFAULT_OUT = (Path(__file__).resolve().parent.parent.parent / "ShortcutsExtracted")


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
        signed_path = signed_dir / f"{safe}.shortcut"
        old_bytes = unsigned_path.read_bytes() if unsigned_path.exists() else None
        workflow.write_unsigned(wf, unsigned_path)
        library.write_action_list(wf, name, actions_dir / f"{safe}.md")
        # The DB's cached ZACTIONCOUNT is unreliable (confirmed stale on
        # live shortcuts) -- only the actually-decoded action list counts.
        if len(wf.get("WFWorkflowActions") or []) == 0:
            empty.append(name)
            continue
        # `shortcuts sign` embeds a fresh nonce/signature every run, so a
        # byte-identical unsigned plist still produces a different signed
        # binary -- re-signing unconditionally would mark every shortcut as
        # changed on every extract-all, even ones that didn't actually
        # change. Only re-sign when the unsigned plist changed, or the
        # signed file doesn't exist yet.
        if old_bytes == unsigned_path.read_bytes() and signed_path.exists():
            continue
        try:
            workflow.sign(unsigned_path, signed_path, mode="anyone")
        except subprocess.CalledProcessError:
            sign_failed.append(name)

    graph_workflows = {
        n: w for n, w in workflows.items() if w is not None and w.get("WFWorkflowActions")
    }
    graph = library.build_full_call_graph(graph_workflows)
    sections, isolated, overview = library.render_mermaid_call_graph(graph)
    lines = ["# Shortcut call graph", ""]
    if overview:
        lines.append(
            "## Overview: every call network, largest first "
            "(jump to its diagram below for the full picture)"
        )
        lines.append("")
        for names, size in overview:
            preview = ", ".join(names) + (", ..." if size > len(names) else "")
            unit = "shortcut" if size == 1 else "shortcuts"
            lines.append(f"- **{size} {unit}** -- {preview}")
        lines.append("")
    for title, mermaid in sections:
        lines.append(f"## {title}")
        lines.append("")
        lines.append(mermaid)
        lines.append("")
    if isolated:
        lines.append(
            f"## Standalone shortcuts ({len(isolated)})"
            " -- call nothing and aren't called by anything, left out of the diagrams above"
        )
        lines.append("")
        for n in isolated:
            lines.append(f"- {n}")
        lines.append("")
    if graph["missing"]:
        lines.append("## Dangling references")
        lines.append("")
        lines.append(
            "These shortcuts are called via Run Shortcut but don't exist in the "
            "library (renamed or deleted):"
        )
        lines.append("")
        for m in graph["missing"]:
            callers = [c for c, callees in graph["edges"].items() if m in callees]
            lines.append(f"- **{m}** -- called by: {', '.join(callers)}")
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


def cmd_folders(args):
    try:
        data = library.export_folder_hierarchy()
    except FileNotFoundError:
        print("osascript not found (this needs to run on macOS).", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(
            "Shortcuts Events didn't respond in time. If this is the first run, "
            "macOS likely needs you to approve an Automation permission prompt "
            "for this process to control Shortcuts.app -- check for a dialog, "
            "approve it, then run this again.",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as e:
        print(f"osascript failed: {e.stderr.strip()}", file=sys.stderr)
        return 1

    out = Path(args.out)
    inventory_dir = out / "inventory"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    (inventory_dir / "folders.json").write_text(json.dumps(data, indent=2))

    by_folder = {}
    for shortcut, folder in data["shortcuts"].items():
        by_folder.setdefault(folder, []).append(shortcut)

    lines = [
        "# Folder hierarchy",
        "",
        f"{len(data['folders'])} folder(s), {len(data['shortcuts'])} shortcut(s).",
        "",
        "Extracted via Shortcuts.app's own AppleScript dictionary, not the "
        "SQLite store -- see `export_folder_hierarchy()` in `library.py` for "
        "why (folder data isn't reachable through Core Data at all).",
        "",
    ]
    for folder in sorted(f["name"] for f in data["folders"]):
        members = sorted(by_folder.get(folder, []))
        lines.append(f"## {folder} ({len(members)})")
        lines.append("")
        for m in members:
            lines.append(f"- {m}")
        lines.append("")
    unfiled = sorted(by_folder.get(None, []))
    if unfiled:
        lines.append(f"## (not in any folder) ({len(unfiled)})")
        lines.append("")
        for m in unfiled:
            lines.append(f"- {m}")
        lines.append("")
    (inventory_dir / "folders.md").write_text("\n".join(lines))

    print(f"{len(data['folders'])} folder(s), {len(data['shortcuts'])} shortcut(s).")
    print(f"Written to {inventory_dir / 'folders.json'} and {inventory_dir / 'folders.md'}")
    return 0


def cmd_automations(args):
    try:
        automations = library.extract_automations()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    out = Path(args.out)
    inventory_dir = out / "inventory"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    (inventory_dir / "automations.json").write_text(
        json.dumps(automations, indent=2, default=library._json_default)
    )

    lines = ["# Personal Automations", "", f"{len(automations)} automation(s).", ""]
    for a in automations:
        lines.append(f"## {a['shortcut_name']}")
        lines.append("")
        lines.append(f"- Trigger: {a['description']} (`{a['trigger_identifier']}`)")
        lines.append("")
    (inventory_dir / "automations.md").write_text("\n".join(lines))

    print(f"{len(automations)} automation(s).")
    print(f"Written to {inventory_dir / 'automations.json'} and {inventory_dir / 'automations.md'}")
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

    p_folders = sub.add_parser(
        "folders",
        help="Export folder membership via Shortcuts.app's own AppleScript dictionary "
        "(needs the Automation permission, not Full Disk Access).",
    )
    p_folders.add_argument("--out", default=str(DEFAULT_OUT))
    p_folders.set_defaults(func=cmd_folders)

    p_automations = sub.add_parser(
        "automations",
        help="Export Personal Automations (trigger condition + the shortcut each one runs).",
    )
    p_automations.add_argument("--out", default=str(DEFAULT_OUT))
    p_automations.set_defaults(func=cmd_automations)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
