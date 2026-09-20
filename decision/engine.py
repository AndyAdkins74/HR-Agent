"""Decision layer.

Takes an email's content (subject, body, sender, attachment filenames) as
plain input and returns a decision plus a reasoning string. This module
has no knowledge of Gmail, OAuth, or any specific mail system -- it would
work identically fed content from a different connector.

Classification judgement (is this HR-related, what to do with any
attachment) is delegated to the Claude API rather than keyword/filename
matching. The prompt text, HR criteria, and folder-mapping rules used to
build that judgement live in config/rules.json (config.rules), not here,
so they can be edited from the control panel without touching this file.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

import anthropic

from config import settings
from config.rules import load_rules


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
    folder_category: str = "default"
    reasoning: str = ""


def _build_system_prompt(rules: Dict[str, Any]) -> str:
    criteria_bullets = "\n".join(f"- {c}" for c in rules.get("hr_criteria", []))
    return rules.get("classification_prompt", "").replace("{criteria}", criteria_bullets)


def _build_classify_tool(rules: Dict[str, Any]) -> Dict[str, Any]:
    folder_categories = list(rules.get("folder_mappings", {}).keys()) or ["default"]
    return {
        "name": "submit_hr_triage_decision",
        "description": "Submit the triage decision for a single email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_hr_related": {
                    "type": "boolean",
                    "description": "True if the email meets the configured HR criteria.",
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
                        "should be saved. Empty if none."
                    ),
                },
                "folder_category": {
                    "type": "string",
                    "enum": folder_categories,
                    "description": (
                        "Which configured folder category attachments_to_save "
                        "belong in. Ignored when attachments_to_save is empty."
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
            "required": [
                "is_hr_related",
                "action",
                "attachments_to_save",
                "folder_category",
                "reasoning",
            ],
        },
    }


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
        folder_category=data.get("folder_category", "default"),
        reasoning=data.get("reasoning", ""),
    )


def classify(email: EmailInput) -> Decision:
    """Classify a single email and decide on an action, using the Claude API."""
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set; the decision layer cannot call Claude."
        )

    rules = load_rules()
    system_prompt = _build_system_prompt(rules)
    classify_tool = _build_classify_tool(rules)

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=1024,
        system=system_prompt,
        tools=[classify_tool],
        tool_choice={"type": "tool", "name": "submit_hr_triage_decision"},
        messages=[{"role": "user", "content": _build_user_message(email)}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_hr_triage_decision":
            return _decision_from_tool_input(block.input)

    raise RuntimeError("Claude did not return the expected tool_use decision block.")
