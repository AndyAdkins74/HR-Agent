"""Decision layer.

Takes an email's content (subject, body, sender, attachment filenames) as
plain input and returns a decision plus a reasoning string. This module
has no knowledge of Gmail, OAuth, or any specific mail system -- it would
work identically fed content from a different connector.

Classification happens in up to two Claude calls:
1. An orchestrator call routes the email to one configured sub-agent (or
   "none" if it isn't HR-related at all -- in which case there's no
   second call).
2. If routed, that sub-agent's own, fully self-contained prompt makes the
   actual triage decision (action, attachments, folder category).

The orchestrator prompt and each sub-agent's prompt live in
config/rules.json (config.rules), not here, so they can be edited from
the control panel without touching this file.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    subagent: str = "none"


def _build_orchestrator_prompt(rules: Dict[str, Any], sub_agents: List[Dict[str, str]]) -> str:
    agent_bullets = "\n".join(f"- {a['name']}: {a['description']}" for a in sub_agents)
    return rules.get("orchestrator_prompt", "").replace("{agents}", agent_bullets)


def _build_route_tool(sub_agents: List[Dict[str, str]]) -> Dict[str, Any]:
    names = [a["name"] for a in sub_agents] + ["none"]
    return {
        "name": "route_to_subagent",
        "description": "Route this email to the sub-agent that should handle it, or 'none'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subagent": {
                    "type": "string",
                    "enum": names,
                    "description": "Name of the sub-agent to hand this email to, or 'none'.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "One sentence explaining the routing choice.",
                },
            },
            "required": ["subagent", "reasoning"],
        },
    }


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


def _decision_from_tool_input(data: Dict[str, Any], subagent: str) -> Decision:
    return Decision(
        is_hr_related=bool(data.get("is_hr_related", False)),
        action=data.get("action", "none"),
        attachments_to_save=list(data.get("attachments_to_save", [])),
        folder_category=data.get("folder_category", "default"),
        reasoning=data.get("reasoning", ""),
        subagent=subagent,
    )


def _extract_tool_input(response, tool_name: str) -> Dict[str, Any]:
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    raise RuntimeError(f"Claude did not return the expected {tool_name} tool_use block.")


def classify(email: EmailInput) -> Decision:
    """Classify a single email and decide on an action, using the Claude API.

    First asks the orchestrator which sub-agent (if any) should handle the
    email; only if one is chosen does a second call ask that sub-agent for
    the actual triage decision. An orchestrator verdict of "none" short-
    circuits before that second call, since there's nothing further to
    decide.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set; the decision layer cannot call Claude."
        )

    rules = load_rules()
    sub_agents = rules.get("sub_agents", [])
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    user_message = _build_user_message(email)

    route_response = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=512,
        system=_build_orchestrator_prompt(rules, sub_agents),
        tools=[_build_route_tool(sub_agents)],
        tool_choice={"type": "tool", "name": "route_to_subagent"},
        messages=[{"role": "user", "content": user_message}],
    )
    route = _extract_tool_input(route_response, "route_to_subagent")
    chosen_name = route.get("subagent", "none")

    sub_agent = next((a for a in sub_agents if a["name"] == chosen_name), None)
    if sub_agent is None:
        return Decision(
            is_hr_related=False,
            action="none",
            reasoning=route.get("reasoning", ""),
            subagent="none",
        )

    classify_tool = _build_classify_tool(rules)
    decision_response = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=1024,
        system=sub_agent["prompt"],
        tools=[classify_tool],
        tool_choice={"type": "tool", "name": "submit_hr_triage_decision"},
        messages=[{"role": "user", "content": user_message}],
    )
    decision_input = _extract_tool_input(decision_response, "submit_hr_triage_decision")
    return _decision_from_tool_input(decision_input, subagent=sub_agent["name"])
