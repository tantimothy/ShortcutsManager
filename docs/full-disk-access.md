# Full Disk Access: what actually needs it, and how it fails

Only one thing in this project touches the protected Shortcuts library:
reading `~/Library/Shortcuts/Shortcuts.sqlite` (`library.py`'s `inspect`,
`dump-raw`, `list-shortcuts`, `extract-one`, `map-calls`, `extract-all`).
Building, signing, and opening `.shortcut` files never needs it.

## Grant it to the right process

TCC's "Full Disk Access" is checked against whichever process actually
calls into SQLite -- not whichever process you *think* is running the
command:

- Running `python3 -m shortcuts_manager.cli ...` yourself in Terminal:
  grant Full Disk Access to **Terminal** (System Settings -> Privacy &
  Security -> Full Disk Access).
- Running it through an assistant whose shell is a child process of
  another app (e.g. the Claude desktop app): grant it to **that app**
  instead -- or just run the command yourself in your own Terminal and
  skip granting it to the assistant at all. Either works; nothing about
  the tool cares who ran it.

## `stat` succeeding does not mean it will work

This bit us directly while debugging why `extract-all` suddenly stopped
working mid-session:

```python
>>> Path("~/Library/Shortcuts/Shortcuts.sqlite").expanduser().exists()
True        # looks fine!
>>> list(Path("~/Library/Shortcuts").expanduser().iterdir())
PermissionError: [Errno 1] Operation not permitted
>>> sqlite3.connect("file:...Shortcuts.sqlite?mode=ro", uri=True)
sqlite3.DatabaseError: authorization denied
```

TCC gates **directory enumeration** (`iterdir()`, `rglob()`) and actually
**opening the file's contents** (`sqlite3.connect()`) separately from a
plain `stat`/`exists()` check, which can succeed either way. `find_stores()`
/ `find_main_store()` in `library.py` rely on `rglob()`, so when Full Disk
Access isn't granted to the calling process, they silently return nothing
(not an exception) and every CLI command fails with "No Shortcuts library
store found" -- which looks like a missing-file error, not a permissions
error. If you see that message and you're sure the file is there, this is
why. There is no code-level workaround; it has to be granted in System
Settings, to the process that's actually calling in.
