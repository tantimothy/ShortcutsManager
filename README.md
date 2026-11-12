# ShortcutsManager

Python tooling for building and signing macOS/iOS Shortcuts (`.shortcut`)
files programmatically, without going through Shortcuts.app's UI.

## How Shortcuts storage actually works

There are two separate layers, confirmed by inspecting this Mac:

1. **Each individual shortcut is a plist.** The action graph (`WFWorkflow...`
   dictionary: `WFWorkflowActions`, icon, client version, etc.) is a binary
   plist. This is the layer this project reads and writes.

2. **The app's library index is a private Core Data/SQLite store**, in
   `~/Library/Group Containers/group.com.apple.shortcuts` (and the legacy
   `group.is.workflow.shortcuts`). It tracks folders, ordering, run history,
   and iCloud sync state for *all* your shortcuts, with the actual action
   data embedded as BLOBs. It's readable (with Full Disk Access granted to
   whatever tool you use) but undocumented, versioned per-OS, and tied into
   CloudKit sync tokens — this project deliberately does not write to it.
   Treat it as read-only/forensic if you ever need to inspect it; build and
   import shortcuts the supported way instead (below).

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

## Requirements

- macOS 12+ (for `/usr/bin/shortcuts`)
- Python 3

Full Disk Access is **not** required for anything in this project — it only
touches files you point it at, never the protected library store.
