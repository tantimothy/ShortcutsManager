"""Build, sign, and read macOS/iOS Shortcuts (.shortcut) files.

A .shortcut file is a binary plist (WFWorkflow...) optionally wrapped in a
CMS/PKCS#7 signature (that's what `shortcuts sign` adds, and what lets
Shortcuts.app trust and run it). This module builds the plist directly,
shells out to the `shortcuts` CLI to sign it, and uses `security cms -D`
to unwrap a signed file back to its plist for reading.
"""

import plistlib
import subprocess
from pathlib import Path

CLIENT_VERSION = "2302.0.5"
CLIENT_RELEASE = "17.0"
MINIMUM_CLIENT_VERSION = 900


def action(identifier, parameters=None):
    """One entry of WFWorkflowActions."""
    return {
        "WFWorkflowActionIdentifier": identifier,
        "WFWorkflowActionParameters": parameters or {},
    }


def new_workflow(actions, icon_start_color=4282601983, icon_glyph_number=61440):
    """A minimal WFWorkflow dict ready to be written out as a plist."""
    return {
        "WFWorkflowActions": actions,
        "WFWorkflowClientVersion": CLIENT_VERSION,
        "WFWorkflowClientRelease": CLIENT_RELEASE,
        "WFWorkflowMinimumClientVersion": MINIMUM_CLIENT_VERSION,
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": icon_start_color,
            "WFWorkflowIconGlyphNumber": icon_glyph_number,
        },
        "WFWorkflowTypes": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowImportQuestions": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowHasShortcutInputVariables": False,
        "WFWorkflowOutputContentItemClasses": [],
    }


def write_unsigned(workflow, path):
    """Write a workflow dict out as a binary plist (unsigned .shortcut)."""
    path = Path(path)
    with open(path, "wb") as f:
        plistlib.dump(workflow, f, fmt=plistlib.FMT_BINARY)
    return path


def sign(input_path, output_path, mode="anyone"):
    """Sign an unsigned .shortcut/.plist via the `shortcuts` CLI.

    mode: "anyone" or "people-who-know-me".
    """
    subprocess.run(
        ["shortcuts", "sign", "-m", mode, "-i", str(input_path), "-o", str(output_path)],
        check=True,
        capture_output=True,
    )
    return Path(output_path)


def read_shortcut(path):
    """Read a .shortcut file back into a workflow dict.

    Unsigned files (and the older, CMS-signed share format) are plain or
    CMS-wrapped plists and decode directly. Current `shortcuts sign` output
    is an Apple Encrypted Archive (magic b"AEA1", profile 0: signed-only,
    not encrypted) whose ECDSA verification key lives in its own embedded
    cert chain -- unwrapping that is out of scope here; use `shortcuts view
    <path>` to inspect a signed file in Shortcuts.app instead.
    """
    data = Path(path).read_bytes()
    if data[:4] == b"AEA1":
        raise NotImplementedError(
            "This is an Apple Encrypted Archive-signed .shortcut (current "
            "`shortcuts sign` output). Use `shortcuts view <path>` to inspect "
            "it, or read_shortcut() on the unsigned plist before signing."
        )
    try:
        return plistlib.loads(data)
    except Exception:
        pass
    result = subprocess.run(
        ["security", "cms", "-D", "-i", str(path)],
        check=True,
        capture_output=True,
    )
    return plistlib.loads(result.stdout)


def build_and_sign(workflow, out_path, mode="anyone", tmp_path=None):
    """Convenience: write workflow unsigned, sign it, return the signed path."""
    out_path = Path(out_path)
    tmp_path = Path(tmp_path) if tmp_path else out_path.with_suffix(".unsigned.shortcut")
    write_unsigned(workflow, tmp_path)
    signed = sign(tmp_path, out_path, mode=mode)
    tmp_path.unlink(missing_ok=True)
    return signed
