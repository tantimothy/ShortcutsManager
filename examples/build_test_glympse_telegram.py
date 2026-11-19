"""Builds a test shortcut that shares a Glympse live-location link via
Telegram instead of letting the Glympse app send it itself (SMS/iMessage).

The trick: Glympse's recipients array supports a `"type": "clipboard"`
entry (see https://developer.glympse.com/docs/core/app/schema/reference,
"Recipients Field" table) -- "The Glympse URL is copied to the clipboard"
instead of being sent to anyone. So: build the same glympse3:// URL the
real Davina/Seletar shortcuts build (via Glympse Input's exact pattern),
but with recipients=[{"type":"clipboard"}], wait for Glympse to return,
read the link back off the clipboard, then open Telegram's own share
scheme (tg://msg_url?url=...&text=...) with that link pre-filled. Telegram
has no URL-scheme way to auto-send without a bot/token, so this opens
Telegram's contact picker with the message ready -- you still tap Send.

There's already a "Test Send Glympse URL" shortcut in the library using a
different, simplified scheme (glympse://?rec_type=clipboard&...,
Openxcallbackurl) -- that one is unverified scratch work (empty params on
the x-callback action). This build instead clones Glympse Input's actual
production-proven URL shape (glympse3://, full recipients JSON array,
plain Open URL + Wait to Return) and only swaps the recipient type, to
maximize the odds the Glympse side of this actually works.

Run (needs the `shortcuts` CLI, i.e. run this on the Mac, not over SSH):
    python3 examples/build_test_glympse_telegram.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortcuts_manager import action, new_workflow, write_unsigned, sign

OUT_DIR = Path(__file__).resolve().parent
TEST_ADDRESS = "Marina Bay Sands, Singapore"  # obviously-public landmark, not a real address of the owner's
TELEGRAM_BLURB = "Here's my live location, tap to view:"


def literal(text):
    return {"Value": {"attachmentsByRange": {}, "string": text}, "WFSerializationType": "WFTextTokenString"}


def var_ref(name):
    return {"Value": {"Type": "Variable", "VariableName": name}, "WFSerializationType": "WFTextTokenAttachment"}


def output_ref(output_name, uuid):
    return {
        "Value": {"OutputName": output_name, "OutputUUID": uuid, "Type": "ActionOutput"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def single_attachment_text(output_name, uuid):
    """A WFTextTokenString consisting of nothing but one embedded reference -- the
    shape `urlencode`/`gettext` actions use when their whole input is one variable."""
    return {
        "Value": {
            "attachmentsByRange": {"{0, 1}": {"OutputName": output_name, "OutputUUID": uuid, "Type": "ActionOutput"}},
            "string": "￼",
        },
        "WFSerializationType": "WFTextTokenString",
    }


def template_text(template, **named_refs):
    """`template` has one '￼' placeholder per kwarg, in order; each kwarg value
    is a {"Type": "Variable", "VariableName": ...} or ActionOutput ref dict."""
    attachments = {}
    pos = 0
    refs = iter(named_refs.values())
    out = []
    i = 0
    while i < len(template):
        if template[i] == "￼":
            attachments[f"{{{pos}, 1}}"] = next(refs)
            pos += 1
        else:
            pos += 1
        out.append(template[i])
        i += 1
    return {
        "Value": {"attachmentsByRange": attachments, "string": template},
        "WFSerializationType": "WFTextTokenString",
    }


actions = []

# 1. Destination: hardcoded test address -> geocoded via the existing shared
#    "Glympse Serialise Destination" building block (same call Glympse Input makes).
a = action("is.workflow.actions.gettext", {"WFTextActionText": literal(TEST_ADDRESS)})
a["WFWorkflowActionParameters"]["UUID"] = (addr_uuid := "10000000-0000-0000-0000-000000000001")
actions.append(a)

a = action(
    "is.workflow.actions.runworkflow",
    {
        "WFInput": output_ref("Text", addr_uuid),
        "WFShowWorkflow": False,
        "WFWorkflow": {"isSelf": False, "workflowName": "Glympse Serialise Destination"},
        "WFWorkflowName": "Glympse Serialise Destination",
    },
)
a["WFWorkflowActionParameters"]["UUID"] = (dest_result_uuid := "10000000-0000-0000-0000-000000000002")
actions.append(a)

a = action("is.workflow.actions.urlencode", {"WFInput": single_attachment_text("Shortcut Result", dest_result_uuid)})
a["WFWorkflowActionParameters"]["UUID"] = (dest_enc_uuid := "10000000-0000-0000-0000-000000000003")
actions.append(a)

actions.append(
    action("is.workflow.actions.setvariable", {"WFInput": output_ref("URL Encoded Text", dest_enc_uuid), "WFVariableName": "Destination"})
)

# 2. Name: pulled out of the same destination-serialization result.
a = action("is.workflow.actions.getvalueforkey", {"WFDictionaryKey": "name", "WFInput": output_ref("Shortcut Result", dest_result_uuid)})
a["WFWorkflowActionParameters"]["UUID"] = (name_uuid := "10000000-0000-0000-0000-000000000004")
actions.append(a)

a = action("is.workflow.actions.urlencode", {"WFInput": single_attachment_text("Dictionary Value", name_uuid)})
a["WFWorkflowActionParameters"]["UUID"] = (name_enc_uuid := "10000000-0000-0000-0000-000000000005")
actions.append(a)

actions.append(
    action("is.workflow.actions.setvariable", {"WFInput": output_ref("URL Encoded Text", name_enc_uuid), "WFVariableName": "Name"})
)

# 3. Recipients: literal single-entry array with the "clipboard" type instead of
#    the real "sms" dictionaries Glympse Phone Number To List would normally build.
a = action("is.workflow.actions.gettext", {"WFTextActionText": literal('[{"type":"clipboard"}]')})
a["WFWorkflowActionParameters"]["UUID"] = (recip_uuid := "10000000-0000-0000-0000-000000000006")
actions.append(a)

a = action("is.workflow.actions.urlencode", {"WFInput": single_attachment_text("Text", recip_uuid)})
a["WFWorkflowActionParameters"]["UUID"] = (recip_enc_uuid := "10000000-0000-0000-0000-000000000007")
actions.append(a)

actions.append(
    action("is.workflow.actions.setvariable", {"WFInput": output_ref("URL Encoded Text", recip_enc_uuid), "WFVariableName": "Recipients"})
)

# 4. Assemble the glympse3:// URL -- identical shape to Glympse Input's own.
glympse_template = "glympse3:?src=shortcut&recipients=￼&dur_mins=80&destination=￼&name=￼&ret_url=workflow://"
a = action(
    "is.workflow.actions.gettext",
    {
        "WFTextActionText": template_text(
            glympse_template,
            recipients={"Type": "Variable", "VariableName": "Recipients"},
            destination={"Type": "Variable", "VariableName": "Destination"},
            name={"Type": "Variable", "VariableName": "Name"},
        )
    },
)
a["WFWorkflowActionParameters"]["UUID"] = (glympse_text_uuid := "10000000-0000-0000-0000-000000000008")
actions.append(a)

actions.append(
    action("is.workflow.actions.setvariable", {"WFInput": output_ref("Text", glympse_text_uuid), "WFVariableName": "glympseURL"})
)

# 5. Open it, and wait for Glympse to hand control back (ret_url=workflow://).
a = action("is.workflow.actions.url", {"Show-WFURLActionURL": True, "WFURLActionURL": var_ref("glympseURL")})
a["WFWorkflowActionParameters"]["UUID"] = (url_action_uuid := "10000000-0000-0000-0000-000000000009")
actions.append(a)

actions.append(action("is.workflow.actions.openurl", {"Show-WFInput": True, "WFInput": output_ref("URL", url_action_uuid)}))
actions.append(action("is.workflow.actions.waittoreturn", {}))

# 6. Read the Glympse link back off the clipboard.
a = action("is.workflow.actions.getclipboard", {})
a["WFWorkflowActionParameters"]["UUID"] = (clip_uuid := "10000000-0000-0000-0000-00000000000a")
actions.append(a)

actions.append(action("is.workflow.actions.setvariable", {"WFInput": output_ref("Clipboard", clip_uuid), "WFVariableName": "GlympseLink"}))

# 7. Build Telegram's share-sheet URL: tg://msg_url?url=<link>&text=<blurb>.
a = action("is.workflow.actions.urlencode", {"WFInput": literal(TELEGRAM_BLURB)})
a["WFWorkflowActionParameters"]["UUID"] = (blurb_enc_uuid := "10000000-0000-0000-0000-00000000000b")
actions.append(a)

actions.append(
    action("is.workflow.actions.setvariable", {"WFInput": output_ref("URL Encoded Text", blurb_enc_uuid), "WFVariableName": "TelegramText"})
)

a = action("is.workflow.actions.urlencode", {"WFInput": var_ref("GlympseLink")})
a["WFWorkflowActionParameters"]["UUID"] = (link_enc_uuid := "10000000-0000-0000-0000-00000000000c")
actions.append(a)

actions.append(
    action("is.workflow.actions.setvariable", {"WFInput": output_ref("URL Encoded Text", link_enc_uuid), "WFVariableName": "LinkEncoded"})
)

telegram_template = "tg://msg_url?url=￼&text=￼"
a = action(
    "is.workflow.actions.gettext",
    {
        "WFTextActionText": template_text(
            telegram_template,
            url={"Type": "Variable", "VariableName": "LinkEncoded"},
            text={"Type": "Variable", "VariableName": "TelegramText"},
        )
    },
)
a["WFWorkflowActionParameters"]["UUID"] = (tg_text_uuid := "10000000-0000-0000-0000-00000000000d")
actions.append(a)

actions.append(action("is.workflow.actions.setvariable", {"WFInput": output_ref("Text", tg_text_uuid), "WFVariableName": "telegramURL"}))

# 8. Open Telegram with it, then show both URLs so you can see what happened.
a = action("is.workflow.actions.url", {"Show-WFURLActionURL": True, "WFURLActionURL": var_ref("telegramURL")})
a["WFWorkflowActionParameters"]["UUID"] = (tg_url_action_uuid := "10000000-0000-0000-0000-00000000000e")
actions.append(a)

actions.append(action("is.workflow.actions.openurl", {"Show-WFInput": True, "WFInput": output_ref("URL", tg_url_action_uuid)}))

debug_template = "Glympse link from clipboard:\n￼\n\nTelegram URL opened:\n￼"
actions.append(
    action(
        "is.workflow.actions.showresult",
        {
            "Text": template_text(
                debug_template,
                link={"Type": "Variable", "VariableName": "GlympseLink"},
                tg={"Type": "Variable", "VariableName": "telegramURL"},
            )
        },
    )
)

workflow = new_workflow(actions)

unsigned = OUT_DIR / "Test Glympse Telegram.unsigned.shortcut"
signed = OUT_DIR / "Test Glympse Telegram.shortcut"
write_unsigned(workflow, unsigned)
sign(unsigned, signed, mode="anyone")
unsigned.unlink()

print(f"Built: {signed}")
