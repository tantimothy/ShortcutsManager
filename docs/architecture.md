# Module reference

High-level overview is in the root [README](../README.md). This is the
per-module reference for finding your way around the code.

## `shortcuts_manager/workflow.py`

The build/sign/read primitives. Everything else is built on these four:

- `action(identifier, parameters=None)` -- one `WFWorkflowActions` entry.
- `new_workflow(actions, icon_start_color=..., icon_glyph_number=...)` --
  wraps a list of actions into a full `WFWorkflow` dict (icon, client
  version, import questions, etc.) ready for `write_unsigned()`.
- `write_unsigned(workflow, path)` -- writes the dict as a binary plist.
- `sign(input_path, output_path, mode="anyone")` -- shells out to
  `/usr/bin/shortcuts sign`. Produces an Apple Encrypted Archive (see
  README's "Signing format"), not a readable plist.
- `read_shortcut(path)` -- reads an **unsigned** plist back into a dict.
  Raises a clear error if pointed at a signed file (can't be read back
  this way -- use `shortcuts view <name>` once imported instead).
- `build_and_sign(workflow, out_path, mode="anyone", tmp_path=None)` --
  convenience wrapper: write unsigned to a temp path, sign, clean up.

## `shortcuts_manager/actions.py`

A handful of example action builders (`show_result`, `comment`, `text`,
`alert`) -- thin wrappers around `action(identifier, parameters)` for
common cases. Add more by finding the action's identifier and parameter
keys from a real extracted shortcut (`extract-one`, or `library.py`'s
`describe_action` output) and wrapping them the same way.

## `shortcuts_manager/nsarchive.py`

`loads(data)` decodes `NSKeyedArchiver`-wrapped plist blobs back into
plain dicts/lists/values -- needed because some Core Data "transformable"
columns in the Shortcuts library store are archived this way rather than
being plain plists. Walks the archive's object graph (`_resolve` /
`_resolve_object`), resolving `$class`/`$objects` references and cycles
via a memo dict. You shouldn't need to call this directly; `library.py`
uses it internally where needed.

## `shortcuts_manager/library.py`

Everything that reads the live Shortcuts app library
(`~/Library/Shortcuts/Shortcuts.sqlite` -- see
[`full-disk-access.md`](full-disk-access.md) for the permission it needs).
Read-only; never writes to the store. Roughly three groups of functions:

**Raw store access**
- `find_stores()` / `find_main_store()` -- locate the SQLite file(s).
- `inspect_schema(db_path)`, `dump_raw(db_path, out_dir)` -- forensic
  dump of every table, for `inspect` / `dump-raw`.

**Reconstructing shortcuts**
- `list_shortcuts(db_path=None)` -- every non-tombstoned shortcut's name
  (filters out CloudKit sync-conflict duplicate rows via
  `ZCONFLICTOF IS NULL`).
- `extract_workflow(name, db_path=None)` -- joins `ZSHORTCUT` ->
  `ZSHORTCUTACTIONS` (plain-plist `ZDATA`, no archiver wrapping) ->
  `ZSHORTCUTICON` and returns a `WFWorkflow` dict shaped exactly like
  `new_workflow()`'s output. Returns `None` if the shortcut can't be
  reconstructed (missing actions row, decode failure) -- callers should
  report this, not silently skip it.
- `extract_all_workflows(db_path=None)` -- the above for every shortcut,
  `{name: dict_or_None}`.

**Call graph and human-readable rendering**
- `find_called_shortcuts(actions)` -- which other shortcuts a `Run
  Shortcut` action list calls, by static name only (skips dynamic/
  variable-based targets -- those can't be resolved without running it).
- `build_call_graph(root_name, ...)` / `build_full_call_graph(workflows)`
  -- BFS out from one shortcut, or build the whole library's graph at
  once. Result includes a `missing` set: names referenced via Run
  Shortcut that don't exist in the library (renamed/deleted).
- `render_mermaid_call_graph(graph, max_cluster_size=12)` -- splits the
  graph into per-connected-component Mermaid diagrams (hub-slicing any
  cluster bigger than `max_cluster_size`), plus a size-ranked overview
  and the isolated (calls nothing, called by nothing) list. Returns
  `(sections, isolated, overview)`.
- `describe_action(action)` -- one pseudocode line for a single action
  (If/Otherwise/End If, Repeat/End Repeat, etc. -- the caller handles
  indentation). `write_action_list(workflow, name, out_path)` renders a
  whole shortcut's actions this way into a fenced-code-block Markdown
  file.

## `shortcuts_manager/cli.py`

Thin argparse wrapper over `library.py`. `DEFAULT_OUT` (currently
`<PROJECTS_DIR>/ShortcutsExtracted`) is where every command
writes by default; override with `--out`. See the root README's command
examples, or `python3 -m shortcuts_manager.cli <command> --help`.

`extract-all` is the one most worth understanding end-to-end: for every
shortcut it writes `unsigned/<name>.shortcut`, signs it to
`signed/<name>.shortcut` (skipping genuinely-0-action shortcuts -- the
DB's cached action count is unreliable, only the actually-decoded list
counts), writes `inventory/actions/<name>.md`, and finally builds and
writes the whole-library `inventory/call_graph.md`.

Re-signing is skipped when the unsigned plist didn't actually change
(byte-for-byte) and a signed file already exists. `shortcuts sign` embeds
a fresh nonce/signature on every run, so signing unconditionally would
make every shortcut in `signed/` show as changed on every `extract-all`,
even ones that didn't change at all -- pure git noise. This means a
shortcut's `signed/` file can lag behind a previous extraction's nonce
until it actually changes; that's fine, since the binary still
re-imports correctly either way.
