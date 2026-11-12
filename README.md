# ShortcutsManager

Python tooling for building and signing macOS/iOS Shortcuts (`.shortcut`)
files programmatically, without going through Shortcuts.app's UI.

## How Shortcuts storage actually works

There are two separate layers, confirmed by inspecting this Mac:

1. **Each individual shortcut is a plist.** The action graph (`WFWorkflow...`
   dictionary: `WFWorkflowActions`, icon, client version, etc.) is a binary
   plist. This is the layer this project reads and writes.

2. **The app's library index is a private Core Data/SQLite store**, at
   `~/Library/Shortcuts/Shortcuts.sqlite` (confirmed by inspection — 877
   pages of real data). The Group Containers
   (`group.com.apple.shortcuts`, `group.is.workflow.shortcuts`) also hold
   `*.sqlite` files, but the ones under `Temporary/.../ProgressiveMigration/`
   turned out to be empty 1-page CloudKit migration scratch databases, not
   the library itself. The real store tracks folders, ordering, run
   history, and iCloud sync state for *all* your shortcuts, with the
   actual action data embedded as BLOBs. It's readable (with Full Disk
   Access granted to whatever tool you use) but undocumented, versioned
   per-OS, and tied into CloudKit sync tokens — this project deliberately
   does not write to it. Treat it as read-only/forensic if you ever need
   to inspect it; build and import shortcuts the supported way instead
   (below).

### Signing format

`shortcuts sign` (the CLI, `/usr/bin/shortcuts`, macOS 12+) does **not**
produce a classic CMS/PKCS#7 signature as commonly described online. It
produces an **Apple Encrypted Archive** (magic bytes `AEA1`), profile 0
(`hkdf_sha256_hmac__none__ecdsa_p256` — signed only, not actually encrypted),
with the verifying certificate chain embedded in the archive's own header.

That means a signed `.shortcut` file can't be read back with `plistlib` or
`security cms -D`. [`read_shortcut()`](shortcuts_manager/workflow.py) raises
a clear error if you try, pointing at `shortcuts view <name>` (once
imported) instead. Read back the *unsigned* plist you built, before
signing, if you need to verify what you constructed.

## What's here

- [`shortcuts_manager/workflow.py`](shortcuts_manager/workflow.py) —
  `new_workflow()` / `action()` build a `WFWorkflow` plist dict,
  `write_unsigned()` writes it as a binary plist, `sign()` shells out to
  `shortcuts sign`, `read_shortcut()` reads a plist back.
- [`shortcuts_manager/actions.py`](shortcuts_manager/actions.py) — a few
  example action builders (`show_result`, `comment`, `alert`). Add more by
  copying the pattern: find an action's identifier and parameter keys (from
  a real exported shortcut, or community references like the
  [Shortcuts Actions wiki](https://shortcutsgallery.com)) and wrap them in
  an `action(identifier, parameters)` call.
- [`examples/hello_world.py`](examples/hello_world.py) — builds a one-action
  shortcut, reads it back to confirm the structure, signs it, and opens it
  in Shortcuts.app for you to add.

## Usage

```python
from shortcuts_manager import new_workflow, write_unsigned, sign
from shortcuts_manager.actions import show_result

workflow = new_workflow([show_result("Hello!")])
write_unsigned(workflow, "unsigned.shortcut")
sign("unsigned.shortcut", "MyShortcut.shortcut", mode="anyone")
```

Then `open MyShortcut.shortcut` to trigger the "Add Shortcut" import prompt
in Shortcuts.app.

## Getting a built shortcut onto iOS

No file transfer tooling needed on the happy path: if the Mac and iPhone
share an Apple ID with iCloud Shortcuts sync on, importing on the Mac syncs
it over automatically. Otherwise AirDrop, email, or host the `.shortcut`
file — opening it on iOS shows the same "Add Shortcut" sheet.

## Extracting your existing library (read-only)

[`shortcuts_manager/cli.py`](shortcuts_manager/cli.py) reads the Shortcuts
app's local Core Data/SQLite store (in `~/Library/Group Containers/
group.com.apple.shortcuts` and the legacy `group.is.workflow.shortcuts`)
and dumps it to JSON. It never writes to that store -- see "How Shortcuts
storage actually works" above for why.

```
python3 -m shortcuts_manager.cli inspect    # list tables/columns/row counts
python3 -m shortcuts_manager.cli dump-raw   # dump every row to JSON
```

Both default to writing into `../ShortcutsExtracted` (override with
`--out DIR`). BLOB columns are decoded automatically: Core Data
"transformable" attributes are usually `NSKeyedArchiver`-wrapped plists
([`shortcuts_manager/nsarchive.py`](shortcuts_manager/nsarchive.py) walks
that object graph back into plain dicts/lists), plain plists decode
directly, and anything else falls back to base64 so nothing is lost.

This requires **Full Disk Access** for whichever process actually runs
`python3` -- the Group Containers are TCC-protected and there's no way
around that:
- Running it yourself in Terminal: grant Full Disk Access to **Terminal**
  (System Settings -> Privacy & Security -> Full Disk Access).
- Running it through an assistant whose shell is a child of another app
  (e.g. the Claude desktop app): grant Full Disk Access to **that app**
  instead.

## Editing an existing shortcut

Confirmed by joining the real tables: `ZSHORTCUT` (name, metadata, and
foreign keys) -> `ZSHORTCUTACTIONS` (its `ZDATA` column is a **plain
plist** of `WFWorkflowActions` -- no archiver wrapping) -> `ZSHORTCUTICON`
(`ZBACKGROUNDCOLORVALUE` / `ZGLYPHNUMBER`). `extract_workflow(name)` in
[`shortcuts_manager/library.py`](shortcuts_manager/library.py) does that
join and reconstructs a `WFWorkflow` dict shaped exactly like
`new_workflow()`'s output, ready to feed back into `write_unsigned()` /
`sign()`.

```
python3 -m shortcuts_manager.cli list-shortcuts
python3 -m shortcuts_manager.cli extract-one --name "Hello World"
```

`extract-one` writes an unsigned, directly editable plist to
`ShortcutsExtracted/unsigned/<name>.shortcut`. Edit its
`WFWorkflowActions`, sign it (`shortcuts sign -m anyone -i ... -o ...`),
and `open` it to re-import -- Shortcuts.app will offer to add it as a new
shortcut (same name, so it'll prompt about the existing one rather than
silently overwriting it, since this tool never touches the live store
directly).

## Requirements

- macOS 12+ (for `/usr/bin/shortcuts`)
- Python 3

Full Disk Access is **not** required for anything else in this project --
building, signing, and opening shortcuts only touches files you point it
at, never the protected library store.
