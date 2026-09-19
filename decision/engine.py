"""Decision layer.

Takes an email's content (subject, body, sender, attachment filenames) as
plain input and returns a decision plus a reasoning string. This module
has no knowledge of Gmail, OAuth, or any specific mail system -- it would
work identically fed content from a different connector.

Classification judgement (is this HR-related, what to do with any
attachment) is delegated to the Claude API rather than keyword/filename
matching.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

import anthropic

from config import settings


@dataclass
class EmailInput:
    subject: str
    sender: str
    body: str
    attachment_filenames: List[str] = field(default_factory=list)


@dataclass
class Decision:
    is_hr_related: bool
    action: str  # "none" | "save_attachments" | "flag_for_review"
    attachments_to_save: List[str] = field(default_factory=list)
    reasoning: str = ""


_CLASSIFY_TOOL = {
    "name": "submit_hr_triage_decision",
    "description": "Submit the triage decision for a single email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_hr_related": {
                "type": "boolean",
                "description": (
                    "True if the email concerns HR matters -- e.g. recruitment, "
                    "onboarding, payroll, benefits, leave requests, employee "
                    "relations, policy, or disciplinary matters."
                ),
            },
            "action": {
                "type": "string",
                "enum": ["none", "save_attachments", "flag_for_review"],
                "description": "What the agent should do next.",
            },
            "attachments_to_save": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Filenames, taken from the provided attachment list, that "
                    "should be saved to the HR output folder. Empty if none."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "One or two sentences explaining the decision, referencing "
                    "the specific content that drove it. This is logged for "
                    "audit, so it must stand on its own."
                ),
            },
        },
        "required": ["is_hr_related", "action", "attachments_to_save", "reasoning"],
    },
}

_SYSTEM_PROMPT = (
    "You are an HR triage assistant reviewing one email at a time from a "
    "shared inbox. You are given its subject, sender, body, and a list of "
    "attachment filenames (not the attachment contents). Decide:\n"
    "1. Whether the email is HR-related (recruitment, onboarding, payroll, "
    "benefits, leave, employee relations, policy, disciplinary matters, etc).\n"
    "2. What should happen next: 'none' if no action is needed, "
    "'save_attachments' if the email is HR-related and it has an attachment "
    "worth keeping (e.g. a CV, contract, signed form, ID document), or "
    "'flag_for_review' if it is HR-related but needs a human to look at it "
    "rather than an automatic action.\n"
    "Only list a filename in attachments_to_save if it is HR-related and "
    "plausibly worth keeping -- do not save attachments from unrelated or "
    "promotional email just because one is present.\n"
    "Always call the submit_hr_triage_decision tool with your answer, and "
    "make the reasoning specific enough that someone auditing the log later "
    "can see why you decided what you did."
)


def _build_user_message(email: EmailInput) -> str:
    attachments = ", ".join(email.attachment_filenames) if email.attachment_filenames else "(none)"
    return (
        f"Subject: {email.subject}\n"
        f"From: {email.sender}\n"
        f"Attachments: {attachments}\n\n"
        f"Body:\n{email.body[:6000]}"
    )


def _decision_from_tool_input(data: Dict[str, Any]) -> Decision:
    return Decision(
        is_hr_related=bool(data.get("is_hr_related", False)),
        action=data.get("action", "none"),
        attachments_to_save=list(data.get("attachments_to_save", [])),
        reasoning=data.get("reasoning", ""),
    )


def classify(email: EmailInput) -> Decision:
    """Classify a single email and decide on an action, using the Claude API."""
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set; the decision layer cannot call Claude."
        )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        tools=[_CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "submit_hr_triage_decision"},
        messages=[{"role": "user", "content": _build_user_message(email)}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_hr_triage_decision":
            return _decision_from_tool_input(block.input)

    raise RuntimeError("Claude did not return the expected tool_use decision block.")
