"""A couple of common action builders, as examples of the parameter shapes."""

from .workflow import action


def show_result(text):
    return action("is.workflow.actions.showresult", {"Text": text})


def comment(text):
    return action("is.workflow.actions.comment", {"WFCommentActionText": text})


def alert(text, title=""):
    return action(
        "is.workflow.actions.alert",
        {"WFAlertActionMessage": text, "WFAlertActionTitle": title},
    )
